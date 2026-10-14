# ClearGate image (PRD 8 portability, TR-SEC-07, ADR-34). Build-time network only:
# packages, the spaCy model and the UI dependencies are fetched while building; the
# running service makes no outbound calls (TR-SEC-01).

# ---- web UI (React, live API mode) -------------------------------------------------
FROM node:20.18.1-bookworm-slim AS ui
WORKDIR /ui
COPY cleargate-ui/package.json cleargate-ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY cleargate-ui/ ./
RUN npm run build

# ---- service ------------------------------------------------------------------------
FROM python:3.13.1-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CLEARGATE_DATA_DIR=/data \
    CLEARGATE_TESSERACT_CMD=/usr/bin/tesseract
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY cleargate/ cleargate/
COPY config/ config/
RUN pip install -e . \
    && pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-3.8.0/en_core_web_lg-3.8.0-py3-none-any.whl
COPY --from=ui /ui/dist cleargate-ui/dist
RUN useradd --system --uid 10001 --home-dir /app cleargate \
    && mkdir -p /data && chown cleargate /data && chmod 0700 /data
USER cleargate
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"]
CMD ["cleargate", "serve", "--host", "0.0.0.0", "--port", "8000"]
