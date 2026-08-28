# 4orm machine OAuth contract

4orm now treats OAuth clients as the machine principal. A service token has a
nullable `user_id` and explicit `principal_type`, `subject`, `client_id`, and
`grant_type` fields. Human authorization-code tokens retain their user link and
are returned as an explicit `user` principal. Consumers never need to infer the
principal type from missing profile data.

## Clients and scopes

`oauth2_clients.toml` declares non-secret client capabilities. It does not
contain client secrets, and startup sync never overwrites stored secret hashes.
The existing public PKCE client remains `worldview`. The new registrations are:

| Purpose | Client ID | Subject | Grant/auth | Allowed scopes | Lifetime |
| --- | --- | --- | --- | --- | --- |
| Worldview backend | `worldview-service` | `worldview-service` | `client_credentials`, `client_secret_basic` | `artbin:assets:read artbin:assets:content artbin:wads:inspect` | 600 seconds |
| Artbin introspection | `artbin-resource-server` | `artbin-resource-server` | introspection only, `client_secret_basic` | none | n/a |

Requested scopes must be a subset of the client's configured scopes. An omitted
scope grants the configured set. Unknown or disallowed scopes return
`invalid_scope`; they are not silently removed or broadened. Machine grants do
not issue refresh tokens.

## Token request

```http
POST https://4orm.harrhy.xyz/oauth/token
Authorization: Basic base64(worldview-service:<secret>)
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&scope=artbin%3Aassets%3Aread
```

Representative response:

```json
{
  "token_type": "Bearer",
  "access_token": "<opaque token>",
  "scope": "artbin:assets:read",
  "expires_in": 600
}
```

Worldview must keep both its client secret and access tokens server-side. It can
cache an access token until shortly before `expires_in`.

## Introspection request

```http
POST https://4orm.harrhy.xyz/oauth/introspect
Authorization: Basic base64(artbin-resource-server:<secret>)
Content-Type: application/x-www-form-urlencoded

token=<opaque-access-token>&token_type_hint=access_token
```

An active service token returns:

```json
{
  "active": true,
  "client_id": "worldview-service",
  "sub": "worldview-service",
  "principal_type": "service",
  "scope": "artbin:assets:read",
  "token_type": "Bearer",
  "exp": 1780000000,
  "iat": 1779999400
}
```

Unknown, malformed, expired, revoked, and disabled-client tokens return
`{"active": false}` to an authenticated, authorized caller. Invalid credentials
and clients without introspection permission receive `401`. Responses use
`Cache-Control: no-store`. Artbin should fail closed on errors or timeouts. It
may cache a successful result for at most `min(exp - now, 30 seconds)`, which
creates a maximum 30-second revocation delay at Artbin.

## Secret lifecycle and revocation

Administrators manage confidential credentials in the OAuth clients section of
`/admin`:

- **generate secret** creates a high-entropy secret, stores only a PBKDF2-SHA256
  hash, and displays the value once;
- **rotate secret** creates a new current secret while retaining the old hash;
  both authenticate during the overlap;
- **finish rotation** removes the previous hash;
- **revoke tokens** immediately marks every outstanding token for the client
  revoked;
- **disable** prevents authentication and makes all outstanding tokens inactive.

Removing a client from TOML disables its row and revokes its tokens instead of
deleting credential history. Reintroducing it enables future issuance but does
not revive revoked tokens. Expired and revoked token rows and audit rows are
retained for operational history; this change does not add an automatic cleanup
job.

Audit events cover token issuance, failed token authentication, introspection,
secret lifecycle actions, client disablement, and bulk revocation. Secret and
token values are never included in those events.

## Production rollout

1. Deploy 4orm and run `alembic upgrade head` before serving traffic. The new
   migration is `a41c9e7d2b10`.
2. Start 4orm once so TOML sync creates `worldview-service` and
   `artbin-resource-server`.
3. In `/admin`, generate one secret for each confidential client. Copy each at
   the one-time display.
4. Add the values to the existing Newport 4orm SOPS deployment secret file at
   `~/infra/hosts/newport/secrets/4orm.enc.yaml` under consumer-specific keys;
   suggested names are `WORLDVIEW_4ORM_CLIENT_SECRET` for Worldview and
   `ARTBIN_4ORM_INTROSPECTION_SECRET` for Artbin. The secrets belong in the
   respective consumer containers, not in 4orm's TOML or environment.
5. Configure Worldview with client ID `worldview-service`, token URL
   `https://4orm.harrhy.xyz/oauth/token`, and its allowed scopes.
6. Configure Artbin with client ID `artbin-resource-server` and introspection URL
   `https://4orm.harrhy.xyz/oauth/introspect`.
7. Verify issuance and introspection, then deploy both consumers.

For rotation, generate the new secret, update and restart the consumer, verify
it authenticates, then choose **finish rotation**. Disabling a client or bulk
revoking tokens is immediate inside 4orm; Artbin's optional cache determines the
external delay described above.

The migration intentionally clears any unexpected legacy plaintext client
secret. Existing configured clients are public and have empty secrets, but a
deployment with a private out-of-band legacy client must generate a new secret
after migration.

## Verification

Run:

```sh
uv run ruff check .
uv run pytest -q
uv run python .agents/skills/verify-4orm/scripts/verify_4orm.py
```

The focused machine OAuth, API compatibility, migration, and real-browser admin
flows are included in those checks. Artbin and Worldview still need their own
consumer-side implementations; no files in either repository were changed.
