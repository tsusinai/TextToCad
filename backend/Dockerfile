FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .

ENV ARTIFACT_ROOT=/data/artifacts
ENV CORS_ORIGINS=https://tsusinai.github.io
VOLUME ["/data"]
EXPOSE 8787

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8787"]
