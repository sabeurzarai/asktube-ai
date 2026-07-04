FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
# HuggingFace model cache: persist on the backend_data volume so downloaded
# embedding models survive container restarts and are writable by non-root app.
ENV HF_HOME=/app/data/hf_cache
ENV HF_HUB_DISABLE_SYMLINKS_WARNING=1
ENV TRANSFORMERS_OFFLINE=0

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-cpu.txt requirements.txt ./
# Install CPU-only torch FIRST from the PyTorch CPU index, so that the main
# requirements' sentence-transformers -> torch dependency resolves to this
# small CPU wheel instead of the default CUDA-bundled wheel (~2.5GB).
RUN pip install --no-cache-dir -r requirements-cpu.txt \
    && pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN addgroup --system app \
    && adduser --system --ingroup app app \
    && mkdir -p /app/data/audio_cache /app/data/hf_cache \
    && chown -R app:app /app

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
