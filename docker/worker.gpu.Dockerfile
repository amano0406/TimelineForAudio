FROM nvidia/cuda:12.8.0-cudnn-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        python3 \
        python3-pip \
        python3-venv \
    && ln -sf /usr/bin/python3 /usr/local/bin/python \
    && ln -sf /usr/bin/pip3 /usr/local/bin/pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

COPY worker/requirements-gpu.txt /app/requirements-gpu.txt
RUN pip install --no-cache-dir -r /app/requirements-gpu.txt

COPY worker/ /app/worker/
COPY configs/ /app/config/

ENV PYTHONPATH=/app/worker/src
ENTRYPOINT ["python", "-m", "timeline_for_audio_worker", "daemon", "--poll-interval", "5"]
