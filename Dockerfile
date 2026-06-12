# Onboarder — single-service image: builds the web UI and serves it from the
# FastAPI backend. Suitable for Railway (Dockerfile builder) or any container host.

# 1. Build the frontend (same-origin: API base is empty → calls hit "/").
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
ENV VITE_API_BASE=""
RUN npm run build

# 2. Backend image with the built UI baked in.
FROM python:3.12-slim AS app
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    ONBOARDER_DATA_DIR=/data \
    ONBOARDER_STATIC_DIR=/app/web
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev || uv sync --no-dev
COPY backend/app ./app
COPY --from=web /web/dist ./web
RUN mkdir -p /data
EXPOSE 8000
CMD ["sh", "-c", "uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
