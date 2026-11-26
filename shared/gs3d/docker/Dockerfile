FROM nvidia/cuda:12.4.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TORCH_CUDA_ARCH_LIST="8.6"

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-dev git ninja-build build-essential \
    colmap libgl1 libglib2.0-0 xvfb \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir --upgrade pip && \
    pip3 install --no-cache-dir \
      torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu124

RUN pip3 install --no-cache-dir \
    gsplat==1.4.0 \
    viser \
    scipy \
    plyfile \
    pillow \
    imageio \
    opencv-python-headless

WORKDIR /workspace
