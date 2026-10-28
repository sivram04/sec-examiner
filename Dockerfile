# API image: FastAPI + agents + local models (bge-small, bge-reranker) on CPU.
# Data (corpus, indexes, SQLite stores) is mounted at /app/data, never baked in.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/hf FASTEMBED_CACHE_PATH=/app/.cache/fastembed

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install . uvicorn[standard] fastapi \
    && useradd --create-home desk && mkdir -p /app/data /app/.cache && chown -R desk /app
USER desk

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=4)"
CMD ["uvicorn", "research_desk.api:app", "--host", "0.0.0.0", "--port", "8000"]
