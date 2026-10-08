# Official python image via Google's Docker Hub mirror (no Docker Hub rate limits)
FROM mirror.gcr.io/library/python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run provides $PORT. Data lives in Google Drive; the container disk is temporary.
CMD ["python", "cloud_start.py"]
