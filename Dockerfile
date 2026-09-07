# Multi-stage build using uv for fast, reproducible dependency installation.
FROM python:3.12-slim AS builder

WORKDIR /app

RUN pip install --no-cache-dir uv

# Install dependencies first (cached separately from source changes).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Now install the project itself.
COPY src/ src/
COPY config.yaml ./
RUN uv sync --frozen --no-dev

# --- Final stage ---
FROM python:3.12-slim

WORKDIR /app

RUN useradd -m -u 1000 app && chown -R app:app /app

COPY --from=builder --chown=app:app /app /app

USER app

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8443

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8443/')"

CMD ["second-brain", "serve"]
