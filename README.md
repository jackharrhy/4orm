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
