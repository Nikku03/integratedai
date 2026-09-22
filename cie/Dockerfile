# Company Intelligence Engine API / worker image
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-eng libmagic1 libgl1 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
RUN pip install --no-cache-dir -e ".[embeddings,providers,s3,redis,columnar]"

ENV CIE_MODEL_CACHE=/models CIE_VAULT_PATH=/data/vault
VOLUME ["/data", "/models"]
EXPOSE 8000
CMD ["cie", "serve", "--host", "0.0.0.0", "--port", "8000"]
