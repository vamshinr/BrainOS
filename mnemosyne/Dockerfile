# Mnemosyne API image. Build context is the mnemosyne/ directory.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/models \
    SENTENCE_TRANSFORMERS_HOME=/opt/models \
    HOST=0.0.0.0 \
    PORT=8090

# libgomp1 is required at runtime by torch / onnxruntime (sentence-transformers).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first for layer caching.
COPY requirements.txt /app/mnemosyne/requirements.txt
RUN pip install -r /app/mnemosyne/requirements.txt

# Bake the embedding model into the image so the first request needs no download.
RUN python -c "from sentence_transformers import SentenceTransformer as S; S('all-MiniLM-L6-v2')"

# Application code (secrets and venv excluded via .dockerignore).
COPY . /app/mnemosyne/

EXPOSE 8090
# python -m mnemosyne runs uvicorn on $HOST:$PORT (see mnemosyne/__main__.py)
CMD ["python", "-m", "mnemosyne"]
