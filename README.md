# 4orm

## Stack

- FastAPI
- SQLAlchemy Core
- SQLite
- Jinja templates + plain CSS

## Run

```bash
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

## CLI

Download the portable CLI at <https://4orm.harrhy.xyz/cli>.

The CLI supports publishing pages, managing media, and updating itself with
`4orm update`.

## Central auth migration

`CENTRAL_AUTH_ENABLED=1` routes browser login through Jack Auth. Set
`OIDC_ISSUER=https://auth.jackharrhy.dev`, `OIDC_CLIENT_ID` to the registered 4orm
client and `OIDC_REDIRECT_URI` to this deployment's `/auth/callback` URL.
The client uses discovery, PKCE, state, nonce and signed ID-token validation.
Central sessions expire after at most one hour; local password login is disabled
in this mode. Leaving the flag unset retains the existing login during rollout.

Before enabling it, run the database migration and install the reviewed mapping
with `scripts/link-central-identities.py --manifest PATH --database PATH --apply`.
The private mapping comes from the auth repository's 4orm migration script.
Identity links preserve existing user IDs and content ownership. Matching a
username alone never links an account. Registration and the remaining OAuth
consumers still need migration before retiring the old identity provider.
