FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    YOLO_CONFIG_DIR=/data/models

RUN apt-get update && apt-get install -y --no-install-recommends \
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
