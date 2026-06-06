FROM node:22-bookworm AS frontend-build

WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/backend
ENV PULSEGUARD_HOST=0.0.0.0
ENV PULSEGUARD_PORT=8787
ENV PULSEGUARD_ALERT_DETAIL_BASE_URL=http://localhost:8787
ENV PULSEGUARD_DATA_DIR=/app/data
ENV PULSEGUARD_REPORTS_DIR=/app/reports
ENV PULSEGUARD_STATIC_DIR=/app/frontend/dist

COPY backend/requirements.txt /app/backend/requirements.txt
RUN python -m pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY --from=frontend-build /build/frontend/dist /app/frontend/dist

RUN mkdir -p /app/data /app/reports/screenshots /app/reports/traces /app/reports/responses

EXPOSE 8787
CMD ["sh", "-c", "python -m uvicorn app.main:app --host ${PULSEGUARD_HOST:-0.0.0.0} --port ${PULSEGUARD_PORT:-8787}"]
