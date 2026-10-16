FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    YOLO_CONFIG_DIR=/data/models

# Prefer IPv4 for apt: on IPv6-less Docker networks DNS returns AAAA records
# only, and apt hangs on the unreachable IPv6 route instead of falling back.
RUN echo 'Acquire::ForceIPv4 "true";' > /etc/apt/apt.conf.d/99force-ipv4 \
    && apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 ffmpeg postgresql-client curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY requirements.txt .
# Pin CPU torch before ultralytics/easyocr to avoid multi-GB CUDA wheel downloads.
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir torch torchvision --index-url ${TORCH_INDEX} \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data/media/snapshots /data/media/uploads /data/media/heatmaps /data/models

EXPOSE 8000

# This image is both the cloud API and the on-site agent. The default command is
# the pipeline runner (agent, AGENT_MODE=1); the cloud `backend` and `inference`
# services override it in docker-compose, so `docker run <image>` with agent env
# works as a single-command install (see deploy/agent/README.md).
CMD ["python", "-m", "app.pipeline.runner"]
