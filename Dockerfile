FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core fonts-noto-core fonts-noto-cjk libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 tuyi && useradd --uid 10001 --gid 10001 --no-create-home tuyi
COPY requirements-web.txt ./
RUN pip install -r requirements-web.txt && pip install --no-deps rapidocr-onnxruntime==1.3.8
COPY web.py translation.py image_formats.py ./
COPY static/ ./static/
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=4s --start-period=15s CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).close()"]
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "--timeout", "180", "web:app"]
