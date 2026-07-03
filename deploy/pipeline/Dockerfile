FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

# ── System deps ───────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    # aiortc (WhipSender) deps
    libsrtp2-dev \
    libopus-dev \
    libvpx-dev \
    libavcodec-dev \
    libavformat-dev \
    libavdevice-dev \
    # opencv-headless runtime deps
    libgl1 \
    libglib2.0-0 \
    # ffmpeg — RTSP reading (OpenCV VideoCapture backend) + recording
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# ── Python deps ───────────────────────────────────────────────────────────────
# CPU-only torch — much smaller than the CUDA wheel (~200 MB vs ~2 GB)
RUN pip install --no-cache-dir \
    torch==2.12.1 torchvision==0.27.1 \
    --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir \
    rfdetr==1.8.0 \
    inference==1.3.1 \
    supervision==0.29.0 \
    aiortc==1.14.0 \
    requests \
    numpy

# inference pulls in opencv-python which requires a display server;
# swap it for the headless build
RUN pip uninstall -y opencv-python && \
    pip install --no-cache-dir opencv-python-headless

# ── App ───────────────────────────────────────────────────────────────────────
WORKDIR /app

COPY pipeline/      ./pipeline/
COPY config_manager/ ./config_manager/
COPY bin/pipeline_app.py ./bin/pipeline_app.py
COPY schemas/       ./schemas/

VOLUME ["/app/config", "/app/data"]

ENV CONFIG_PATH=config/sources.json \
    MODEL_WEIGHTS=/app/weights/model.pth \
    WHIP_URL=http://mediamtx:8889/live/whip \
    API_BASE_URL=http://api:8000 \
    PIPELINE_REFRESH_URL=http://pipeline:8001/refresh \
    PIPELINE_RECORD_URL=http://pipeline:8001/record

EXPOSE 8001

CMD ["python3", "bin/pipeline_app.py"]
