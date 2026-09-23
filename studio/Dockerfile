# Verified amd64 tag/digest on 2026-09-23. Actual build remains a required gate.
FROM runpod/pytorch:1.3.2-cu1300-torch2120-ubuntu2404@sha256:41428c446234172cb2700630b81bb55b7077026c7a43cbd2c991fd864e454c61

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 \
    H3MAX_ROOT=/workspace/h3max H3MAX_MODEL_GROUPS=h3 \
    H3MAX_DOWNLOAD_MODELS=1 HF_HUB_DISABLE_TELEMETRY=1 \
    HF_XET_HIGH_PERFORMANCE=1 HF_XET_CHUNK_CACHE_SIZE_BYTES=0 \
    HF_HUB_DOWNLOAD_TIMEOUT=120 HF_HUB_ETAG_TIMEOUT=30

RUN apt-get update && apt-get install -y --no-install-recommends \
      git ffmpeg libgl1 libglib2.0-0 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY . /opt/h3-max
RUN PIP_NO_CACHE_DIR=1 python /opt/h3-max/scripts/install.py \
    && cp /opt/h3-max/post_start.sh /post_start.sh \
    && chmod +x /post_start.sh

EXPOSE 8188
HEALTHCHECK --start-period=3600s --interval=30s --timeout=5s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8188/system_stats', timeout=4)" || exit 1

# Preserve the official image's entrypoint/CMD and SSH/Jupyter initialization.
# Its /start.sh invokes our /post_start.sh after configuring SSH.
