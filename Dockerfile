FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir --upgrade "pip==26.2.2"

COPY --from=ghcr.io/astral-sh/uv:0.13.4 /uv /bin/uv

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock README.md oauth2_clients.toml ./
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

# Exercise the installed runtime verifiers before an image can be published.
COPY scripts/verify_tls.py /usr/local/bin/verify-tls.py
RUN /usr/local/bin/python /usr/local/bin/verify-tls.py \
    && /app/.venv/bin/python /usr/local/bin/verify-tls.py
