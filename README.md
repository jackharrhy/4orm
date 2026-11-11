# 4orm

## Stack

- FastAPI
- SQLAlchemy Core
- SQLite
- Jinja templates + plain CSS

## Run

```bash
uv python install
uv sync
FOURM_ENV=development uv run uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000

## Production configuration

For a production deploy, set a `SECRET_KEY`. You can generate one with
`openssl rand -hex 32`. Keep the same key between deployments so people stay
signed in. Production is the default environment and uses HTTPS-only session
cookies.

Members can use custom HTML, CSS, and JavaScript on their pages. Custom scripts
currently run as part of the main 4orm site, which fits the small, invite-only
community it was built for. If that changes someday, serving member pages from
a separate origin would provide a little more separation from the rest of the
site.

## Central identity

4orm uses `https://auth.jackharrhy.dev` for browser and CLI authentication. Its
built-in authorization server, local password login/reset, client registration,
consent and provider administration are removed. Historical database tables and
migration backups remain available for audit; they cannot authorize requests.
Artbin, Maps and Burger consume central Auth. Worldview was replaced by Maps and
its historical registrations are retired rather than recreated.

Configure `OIDC_ISSUER=https://auth.jackharrhy.dev`, `OIDC_CLIENT_ID` and the exact
registered `OIDC_REDIRECT_URI` ending in `/auth/callback`. Discovery, S256 PKCE,
state, nonce and RS256 ID-token validation establish the member session. Sessions
expire within one hour; existing local user IDs and ownership remain authoritative.
Only explicit `external_identities` issuer/subject links identify members. Names
and email addresses never merge accounts. Admin identity management opens Auth.

New installations need a centrally registered client and reviewed initial identity
links. The production import is complete; subsequent members join through signed
invite enrollment. Do not replay an old identity manifest over current links.

Member invite links stay at `/register?invite=CODE`. Enrollment reserves an invite
for 30 minutes and continues at Auth for account creation and email verification.
Only the verified callback consumes the invite and creates the local profile.
Existing linked members retain their profile without consuming an invite.
Disabled, expired and exhausted invites cannot create members.

Mount the scoped integration JSON key (`{"token":"..."}`) outside source control
and configure `CENTRAL_AUTH_ENROLLMENT_KEY_FILE`; Auth uses the matching
`FOURM_ENROLLMENT_KEY_FILE`. New-profile commit also creates a durable completion
event. Auth processes only Maps/Burger MEMBER eligibility after that commit, with
per-application reservations and terminal receipts. Existing-member re-enrollment
creates no event; completed replay cannot restore a revoked companion grant.
Receipts remain valid after the original invite expires. An ambiguous HTTP 409
requires operator reconciliation. Profile/invite ownership survives broker errors.
Retry pending events in the configured app environment with:

```bash
uv run python scripts/retry-enrollment-completions.py --limit 100
```

## CLI and API

Download the portable CLI at <https://4orm.harrhy.xyz/cli>. It publishes pages,
manages media and updates itself with `4orm update`. Legacy cached credentials
require version 0.4.0 or later and a fresh `4orm login`; tokens are never transferred
or refreshed across issuers.

Set `OIDC_PROJECT_ID`, `OIDC_ORGANIZATION_ID`, `OIDC_CLI_CLIENT_ID` and mount the
BASIC resource client JSON (`clientId`, `clientSecret`) at
`OIDC_API_CREDENTIALS_FILE`. `/api/v1/auth-config` advertises the central native
client/scopes. Authenticated introspection supplies exact scopes and revocation
state. API requests require the central issuer, project audience, human principal,
organization-qualified member role and explicit local identity link. Page/media
operations require both the exact requested permission scope and matching
`pages-read`, `pages-write`, `media-read` or `media-write` role. Local disabled,
admin and content-ownership checks stay authoritative. Provider/configuration
failures fail closed.

Historical provider metadata can be inspected without exporting credentials:
`python scripts/inventory-oauth.py --database PATH`. Audited legacy retirement is
performed only after consumer acceptance and a recoverable backup; keep the first
migration backup intact. `scripts/retire-legacy-oauth.py` defaults to read-only;
`--apply` requires reviewed inventory, accepted client coverage, a current separate
SQLite backup and a new protected receipt path. It verifies removed live issuer
and local-password endpoints before disabling clients, revoking tokens and
expiring any still-valid historical authorization/reset credentials. The audit
event and backup hashes identify the committed operation; do not blindly repeat
a prepared-only receipt.

Maps browser/automation sessions and dynamic MCP clients
must reauthorize centrally; historical bearer credentials are never imported.

## Browser verification

```bash
uv run python .agents/skills/verify-4orm/scripts/verify_4orm.py
```

This uses a disposable loopback HTTPS OIDC provider with signed tokens, temporary
certificate trust and an isolated database. Desktop/mobile screenshots, console
logs and layout assertions are retained under `artifacts/verification/central/`.

## State machines

[State machines](STATE_MACHINES.md) maps authentication, enrollment, content,
browser requests, chat and operations to their owners, transitions and guards.
Run browser-state regressions with `npm run test:web`.
