FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .

ENV ARTIFACT_ROOT=/data/artifacts
ENV CORS_ORIGINS=https://tsusinai.github.io,http://localhost:5173,http://127.0.0.1:5173
VOLUME ["/data"]
EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/health', timeout=3).read()"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8787", "--workers", "1"]
