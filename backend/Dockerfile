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

COPY requirements.txt requirements-local-embeddings.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# To bake the free local-embeddings extras into this image (adds torch,
# ~0.5–2 GB depending on platform), uncomment ONE of the lines below:
#   amd64/x86_64 (CPU-only torch from the PyTorch CPU index, ~200 MB):
#     RUN pip install --no-cache-dir -r requirements-local-embeddings.txt \
#         --extra-index-url https://download.pytorch.org/whl/cpu
#   arm64/aarch64 (plain torch from PyPI is already CPU-only on ARM):
#     RUN pip install --no-cache-dir -r requirements-local-embeddings.txt

COPY app ./app

RUN addgroup --system app \
    && adduser --system --ingroup app app \
    && mkdir -p /app/data/audio_cache /app/data/hf_cache \
    && chown -R app:app /app

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
