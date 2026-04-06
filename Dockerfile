FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Install dependencies first for better layer caching
# (README is required by build metadata during uv sync)
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev

# App source
COPY src/ src/

# Ensure the project package reflects latest source files
RUN uv sync --frozen --no-dev

# Runtime defaults
ENV QBRAIN_DB=/app/data/qbrain.db \
    QBRAIN_EMBED_MODEL=text-embedding-3-small

EXPOSE 8099

CMD ["uv", "run", "qbrain", "serve", "--host", "0.0.0.0", "--port", "8099"]
