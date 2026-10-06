# Render worker: FastAPI + headless PyQGIS (QGIS LTR) with the matplotlib fallback.
# Build:  docker build -t amia-car-maps-worker .     (context = worker/)
# Run:    docker run -p 8001:8001 -e WORKER_TOKEN=... -e SUPABASE_URL=... -e SUPABASE_SERVICE_ROLE_KEY=... <image>
ARG QGIS_IMAGE=qgis/qgis:ltr
FROM ${QGIS_IMAGE}

ENV PYTHONUNBUFFERED=1 \
    QT_QPA_PLATFORM=offscreen \
    QT_QPA_FONTDIR=/app/assets/fonts \
    XDG_RUNTIME_DIR=/tmp/runtime-root \
    QGIS_PYTHON=/usr/bin/python3 \
    OUTPUT_DIR=/data/outputs \
    TZ=Asia/Manila \
    ENV=production

WORKDIR /app
COPY requirements.txt .
# The QGIS image ships GDAL/geos; install the rest with the system Python that has PyQGIS.
RUN python3 -m pip install --no-cache-dir --break-system-packages -r requirements.txt \
 && mkdir -p /usr/share/fonts/truetype/montserrat /data/outputs /tmp/runtime-root
COPY assets/fonts/*.ttf /usr/share/fonts/truetype/montserrat/
RUN fc-cache -f >/dev/null 2>&1 || true

COPY agriclimate ./agriclimate
# download the OCR models at build time (PAGASA seasonal tables)
RUN python3 -c "from rapidocr import RapidOCR; RapidOCR()" || true
COPY scripts ./scripts
COPY data ./data
COPY assets ./assets

EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s CMD python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8001/health')"
CMD ["python3", "-m", "uvicorn", "agriclimate.api:app", "--host", "0.0.0.0", "--port", "8001"]
