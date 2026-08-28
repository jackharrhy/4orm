# Machine identities and expanded OAuth

This is a request for the agent working on 4orm. Artbin and Worldview need a normal OAuth machine-to-machine flow. Browsers must never receive machine credentials.

The earlier idea of adding an Artbin-specific shared token has been rejected. 4orm should remain the identity and credential authority, while Artbin remains the resource server that owns asset authorization.

Please inspect the current implementation, make only the 4orm-side changes you consider correct, and write the resulting OAuth contract and rollout instructions to `MACHINE_USER_EXPANDED_OAUTH_RESPONSE.md` in this repository root. Do not edit Artbin or Worldview as part of this task.

We control all three applications and deploy them together. Do not introduce API version namespaces solely for hypothetical third-party compatibility. Prefer a clean contract that we can change coherently across the repositories.

## Current 4orm capabilities observed by Artbin

Please verify this inventory rather than treating it as authoritative:

- OAuth is implemented with Authlib and SQLAlchemy Core in `app/oauth2.py`.
- Authorization-code + PKCE and refresh-token grants exist.
- OAuth clients are declared in `oauth2_clients.toml` and synchronized at startup.
- Clients have allowed scopes, grant types, response types, token endpoint authentication methods, and optional client secrets.
- Access and refresh tokens are opaque, persisted in `oauth2_tokens`, expire, and can be revoked.
- Tokens currently require a non-null human `user_id`.
- `get_access_token_context` validates token expiry/revocation and resolves an active human user.
- `/oauth/userinfo` is the current token-backed identity surface and is intentionally tied to the `openid` scope.
- There is no client-credentials grant, machine/service principal model, token introspection endpoint, or resource-server validation contract.
- Client secrets appear to be stored and compared as plaintext, and the declarative TOML format permits literal secrets. Production secrets must not be committed.

This is a useful foundation. The goal is to extend it, not create a parallel token system.

## Required use case

The Worldview backend should authenticate to 4orm as a confidential machine client, obtain a short-lived bearer token, and call Artbin with it. Artbin must be able to validate the token and enforce Artbin-specific scopes without sharing 4orm's database.

The intended flow is:

1. Worldview service authenticates to `POST /oauth/token` with its client ID and secret.
2. It requests `grant_type=client_credentials` and a bounded set of Artbin resource scopes.
3. 4orm returns a short-lived bearer token without a refresh token.
4. Worldview caches the token server-side until shortly before expiry.
5. Worldview calls Artbin with `Authorization: Bearer <token>`.
6. Artbin validates or introspects the bearer token with 4orm and enforces the required scope.
7. Revoking/rotating the Worldview machine client in 4orm prevents further token issuance and makes already-issued tokens invalid according to the documented revocation behavior.

No client secret or access token may reach browser JavaScript, project documents, logs, committed configuration, screenshots, or API responses.

## Requested 4orm design

### 1. First-class machine principals

Represent machine identity explicitly. Do not create a fake interactive user with a password and do not overload human-user profile fields merely to satisfy the current non-null `oauth2_tokens.user_id` constraint.

The exact schema is owned by 4orm. A reasonable model is either:

- the OAuth client itself is the machine principal and machine tokens carry `client_id` with no human subject; or
- a separate service-principal table exists and confidential OAuth clients are attached to one principal.

Whichever model is chosen, token validation must return an unambiguous principal type and stable machine subject. Human authorization-code tokens must continue to work without migration surprises.

Suggested normalized identity fields:

```json
{
  "principalType": "service",
  "subject": "worldview-service",
  "clientId": "worldview-service"
}
```

Names may differ if 4orm has an established convention, but consumers must never have to infer machine-versus-human identity from missing profile properties.

### 2. OAuth client-credentials grant

Add standards-conforming `client_credentials` support to `/oauth/token` using Authlib's grant machinery where practical.

Requirements:

- confidential clients only;
- `client_secret_basic` is the preferred token endpoint authentication method;
- reject public clients and `token_endpoint_auth_method=none`;
- grant only the intersection of requested and client-allowed scopes;
- reject unknown or disallowed scopes explicitly rather than silently broadening access;
- issue short-lived access tokens (proposed default: 5–15 minutes);
- do not issue refresh tokens for client-credentials grants;
- persist enough information for expiry, revocation, auditing, and introspection;
- distinguish disabled/revoked clients from invalid credentials without leaking secrets;
- rate-limit repeated failed client authentication if 4orm has or can cleanly add that facility.

The existing interactive `worldview` OAuth client is a browser-facing public client and should remain separate. Add a distinct confidential machine client such as `worldview-service`; do not add a secret to the existing PKCE client.

### 3. Resource scopes

4orm should issue and report scopes; Artbin will define their authorization meaning.

The first Artbin integration needs:

- `artbin:assets:read` — approved catalog search and metadata lookup;
- `artbin:assets:content` — original approved bytes, including ranged delivery;
- `artbin:wads:inspect` — stable WAD directory/texture metadata.

No creation or conversion scope is requested. The three scopes above are the complete initial resource-scope vocabulary 4orm needs to issue for this client.

Scopes must be carried unchanged in the access-token record and returned by the resource-server validation surface. Human tokens should not receive these scopes unless the relevant client is explicitly configured for them.

### 4. Token validation for Artbin

Current access tokens are opaque, so Artbin needs a supported validation surface. Prefer a standards-shaped OAuth token introspection endpoint rather than teaching Artbin about 4orm's database.

Proposed contract:

```http
POST /oauth/introspect
Authorization: Basic <artbin-resource-server credentials>
Content-Type: application/x-www-form-urlencoded

token=<opaque-access-token>&token_type_hint=access_token
```

For an active machine token, return at least:

```json
{
  "active": true,
  "client_id": "worldview-service",
  "sub": "worldview-service",
  "principal_type": "service",
  "scope": "artbin:assets:read artbin:assets:content artbin:wads:inspect",
  "token_type": "Bearer",
  "exp": 1780000000,
  "iat": 1779999400
}
```

Inactive, expired, revoked, malformed, disabled-client, and unknown tokens should return `{ "active": false }` to an authenticated introspection caller. An unauthenticated or unauthorized introspection caller should receive `401` with an appropriate `WWW-Authenticate` challenge.

Only explicitly authorized confidential clients/resource servers may introspect tokens. Add a separate Artbin resource-server credential or another clear authorization mechanism; possession of an ordinary OAuth client credential must not automatically permit introspection.

If the 4orm agent determines that signed JWT access tokens plus a JWKS endpoint are materially better for this small deployment, document that alternative carefully. It must still support prompt client/token revocation or clearly state the bounded revocation delay. Given the existing opaque-token architecture and low service count, introspection appears to be the smallest coherent extension.

### 5. Secret storage, issuance, and rotation

Do not commit production client secrets to `oauth2_clients.toml`.

Please establish a concrete secret-management mechanism compatible with the current container deployment. Possibilities include environment-backed secret references in the declarative client config or an administrative issuance/rotation workflow. The chosen design must provide:

- high-entropy generated secrets;
- one-time display or external secret injection;
- hashed-at-rest client secrets where feasible;
- overlap or an explicitly coordinated cutover for rotation;
- client disable/revocation;
- no secret values in logs;
- a documented setup path for production and local development/tests.

If supporting two concurrent credentials per machine client is excessive, document an exact coordinated rotation procedure and its expected interruption window.

Removing a client from declarative configuration currently appears to delete its client row. Ensure associated tokens are revoked/deleted predictably and that referential behavior does not leave active orphan credentials.

### 6. Revocation and operational semantics

Define and test:

- access-token lifetime;
- what immediately invalidates an access token;
- whether disabling/revoking a machine client invalidates all its outstanding tokens;
- explicit per-token revocation, if supported;
- client-secret rotation behavior;
- cleanup of expired/revoked tokens;
- introspection timeout and failure behavior expected of resource servers;
- audit fields/events for token issuance, failed client authentication, introspection, client disablement, and revocation.

Artbin will fail closed when 4orm cannot validate a token. Because introspection is on the content-request path, keep it inexpensive and document whether Artbin may cache successful introspection results until a small bound such as `min(exp, now + 30 seconds)`. Also document the resulting maximum revocation delay if caching is permitted.

### 7. Error behavior

Use OAuth-compatible errors and status codes at the token endpoint. At minimum, distinguish:

- malformed requests;
- invalid client authentication;
- unauthorized grant type;
- invalid/disallowed scope;
- temporarily unavailable service.

Do not disclose whether a submitted secret was close to or formerly valid.

## Tests expected in 4orm

Please add focused tests for:

- successful client-credentials issuance;
- Basic client authentication and rejection of public clients;
- allowed, omitted, unknown, and disallowed scopes;
- no refresh token in machine grants;
- short-lived expiry;
- machine principal/token persistence without a fake human user;
- active introspection response and exact identity/scope claims;
- inactive responses for expired, revoked, unknown, and disabled-client tokens;
- introspection endpoint authentication/authorization;
- client disablement invalidating outstanding tokens;
- secret comparison/storage behavior;
- rotation behavior;
- preservation of authorization-code, PKCE, refresh-token, userinfo, and existing API behavior;
- configuration synchronization and cleanup semantics.

## Requested response

Write `MACHINE_USER_EXPANDED_OAUTH_RESPONSE.md` when complete. Include:

- the final machine-principal data model;
- final token and introspection endpoints with representative requests/responses;
- client configuration schema;
- how confidential secrets are supplied in production and tests;
- scope rules;
- access-token lifetime and caching guidance;
- rotation, disablement, revocation, and cleanup behavior;
- migration/deployment steps;
- the exact client and resource-server configuration values that consuming services must receive;
- a concise integration checklist for token clients and introspecting resource servers;
- test commands and results;
- any unresolved cross-repository decision.

Keep the response scoped to 4orm: machine principals, OAuth grants, token validation, scopes, credentials, revocation, operations, migrations, and tests. The consuming repositories will make their own application and resource-authorization decisions from that contract.
