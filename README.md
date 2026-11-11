# 4orm

An invite-only community with member pages, a forum and chat. Built with FastAPI,
SQLAlchemy Core, SQLite, Jinja templates and plain CSS.

## Run

```bash
uv python install
uv sync
FOURM_ENV=development uv run uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. Sign-in uses [Jack Auth](https://auth.jackharrhy.dev);
a new installation needs a registered client and explicit identity links.

## Deploy

Set a persistent `SECRET_KEY`, configure the OIDC clients and mount the API and
enrollment credentials outside source control. Production defaults to HTTPS-only
session cookies. See [operations](docs/operations.md) for configuration, invite
recovery and migration records.

Members' custom JavaScript runs on the main site. Keep that in mind before opening
the community beyond trusted members.

## CLI

[Download the CLI](https://4orm.harrhy.xyz/cli) to publish pages and manage media.
Sign in with `4orm login`; update with `4orm update`.

## Check

Run browser-state regressions with `npm run test:web`. For isolated desktop/mobile
browser checks:

```bash
uv run python .agents/skills/verify-4orm/scripts/verify_4orm.py
```

Screenshots and logs go in `artifacts/verification/central/`.
