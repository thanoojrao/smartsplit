# The API (and the CLI) in one image: `docker compose up -d` runs it with Postgres.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.12-slim
RUN useradd --create-home --uid 1000 smartsplit
WORKDIR /app
COPY --from=build --chown=smartsplit:smartsplit /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 SMARTSPLIT_IMAGE_DIR=/data/images
RUN mkdir -p /data/images && chown -R smartsplit:smartsplit /data
USER smartsplit
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz')"
CMD ["uvicorn", "--factory", "smartsplit.entrypoints.api.server:from_environment", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
