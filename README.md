# 4orm

Minimal retro personal-page platform.

## Stack
- FastAPI
- SQLAlchemy Core (no ORM models)
- SQLite
- Jinja templates + plain CSS (no Tailwind)

## Run
```bash
uv sync
uv run uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000

## Notes
- Registration requires an invite code.
- Users are considered trusted: page HTML and custom CSS are stored raw.
- First-time bootstrapping: create an initial user/invite directly in SQLite (or add an admin bootstrap route later).
