ARG BASE_TAG=latest
FROM ghcr.io/lecode-official/comfyui-docker:${BASE_TAG}

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
        comfyui-frontend-package \
        opencv-python-headless \
        diffusers \
        sageattention \
        GitPython \
        requests

RUN pip install --no-cache-dir git+https://github.com/facebookresearch/sam2
