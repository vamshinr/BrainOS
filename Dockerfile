FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps from backend folder
COPY src/python_backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the backend source
COPY src/python_backend/ .

# Persistent data dir (mount a Railway volume here)
RUN mkdir -p /data

ENV BRAIN_DATA_DIR=/data
ENV PORT=8081

EXPOSE 8081

CMD ["python", "main.py"]
