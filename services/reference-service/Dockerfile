# Multi-stage build for reference-service.
# Stage 1 pulls uv + workspace deps; Stage 2 produces a slim runtime image.
FROM python:3.12-slim AS build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir uv==0.11.30

WORKDIR /repo

# Copy workspace metadata first for better layer caching.
COPY pyproject.toml uv.lock* ./
COPY libs/ ./libs/
COPY services/reference-service/ ./services/reference-service/

RUN uv sync --frozen --no-dev --package reference-service

# --- Runtime image ---
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/repo/.venv/bin:$PATH"

RUN useradd --create-home --uid 10001 cip
WORKDIR /repo

COPY --from=build --chown=cip:cip /repo /repo

USER cip
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health/live').status==200 else 1)"

CMD ["uvicorn", "reference_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
