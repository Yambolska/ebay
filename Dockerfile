FROM python:3.12-slim

# Sistem bağımlılıkları (psycopg2 için build araçları lazım olabilir)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY queries.json .
COPY .env .

# 30 dakikada bir çalıştıran basit döngü
CMD sh -c 'while true; do python app.py; sleep 1800; done'

