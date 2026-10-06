# Render worker: FastAPI + matplotlib/geopandas rendering (no QGIS needed).
# Build:  docker build -t amia-car-maps-worker .     (context = worker/)
# Run:    docker run -p 8001:8001 -e WORKER_TOKEN=... -e SUPABASE_URL=... -e SUPABASE_SERVICE_ROLE_KEY=... <image>
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLCONFIGDIR=/tmp/matplotlib \
    MALLOC_ARENA_MAX=2 \
    OUTPUT_DIR=/data/outputs \
    TZ=Asia/Manila \
    ENV=production

# fontconfig: Montserrat for the maps; libgl1/libglib2.0-0: OpenCV (used by the PAGASA OCR)
RUN apt-get update \
 && apt-get install -y --no-install-recommends fontconfig libgl1 libglib2.0-0 tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt \
 && mkdir -p /usr/share/fonts/truetype/montserrat /data/outputs /tmp/matplotlib
COPY assets/fonts/*.ttf /usr/share/fonts/truetype/montserrat/
RUN fc-cache -f >/dev/null 2>&1 || true

COPY agriclimate ./agriclimate
# download the OCR models at build time (PAGASA seasonal tables)
RUN python -c "from rapidocr import RapidOCR; RapidOCR()" || true
COPY scripts ./scripts
COPY data ./data
COPY assets ./assets

EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os,urllib.request;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8001\")}/health')"
# Render (and similar hosts) set PORT; default 8001
CMD ["sh", "-c", "exec python -m uvicorn agriclimate.api:app --host 0.0.0.0 --port ${PORT:-8001}"]
