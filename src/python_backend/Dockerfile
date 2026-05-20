FROM python:3.10-slim

WORKDIR /app

# System deps for chromadb + sentence-transformers
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Data dir for brain.json + chromadb
RUN mkdir -p /data

ENV BRAIN_DATA_DIR=/data
ENV PORT=8081

EXPOSE 8081

CMD ["python", "main.py"]
