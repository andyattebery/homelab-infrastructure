#!/bin/bash
pip install sageattention rotary-embedding-torch

# Remove hipblaslt patch if present from previous runs
sed -i '/preferred_blas_library/d' /root/ComfyUI/main.py
