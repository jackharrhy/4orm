FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY templates ./templates
COPY static ./static
COPY uploads ./uploads
COPY data ./data

RUN mkdir -p /app/backups

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
