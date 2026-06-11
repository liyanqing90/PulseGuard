FROM node:22-bookworm AS frontend-build

WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.9.30 AS uv-bin

FROM mcr.microsoft.com/playwright/python:v1.49.1-noble AS runtime-base

WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/backend
ENV PATH=/app/.venv/bin:$PATH
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV PULSEGUARD_HOST=0.0.0.0
ENV PULSEGUARD_PORT=8787
ENV PULSEGUARD_ALERT_DETAIL_BASE_URL=http://localhost:8787
ENV PULSEGUARD_DATA_DIR=/app/data
ENV PULSEGUARD_REPORTS_DIR=/app/reports
ENV PULSEGUARD_STATIC_DIR=/app/frontend/dist

COPY --from=uv-bin /uv /uvx /bin/
COPY pyproject.toml uv.lock /app/
RUN uv sync --frozen --no-dev --no-install-project

COPY backend /app/backend

RUN mkdir -p /app/data /app/reports/screenshots /app/reports/traces /app/reports/responses

FROM runtime-base AS app

COPY --from=frontend-build /build/frontend/dist /app/frontend/dist

EXPOSE 8787
CMD ["sh", "-c", "uvicorn app.main:app --host ${PULSEGUARD_HOST:-0.0.0.0} --port ${PULSEGUARD_PORT:-8787}"]
