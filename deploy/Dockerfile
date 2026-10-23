# Multi-stage Dockerfile for State-Aware Durable Runtime Server
FROM python:3.11-slim as builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir . && \
    pip install --no-cache-dir fastapi uvicorn[standard] websockets aiofiles

# Production Runtime Image
FROM python:3.11-slim as runtime

WORKDIR /app

# Security: Create non-privileged service user
RUN groupadd -r sadr && useradd -r -g sadr -s /bin/false sadr

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY src/ ./src/
COPY pyproject.toml README.md ./

# Create data directories with appropriate permissions
RUN mkdir -p /app/state /app/logs /app/workspace && \
    chown -R sadr:sadr /app

USER sadr

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    SADR_HOST=0.0.0.0 \
    SADR_PORT=8000 \
    SADR_WORKERS=4 \
    SADR_STORAGE_DIR=/app/state \
    SADR_LOG_DIR=/app/logs \
    SADR_WORKSPACE_DIR=/app/workspace

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

ENTRYPOINT ["uvicorn", "state_aware_runtime.server.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
