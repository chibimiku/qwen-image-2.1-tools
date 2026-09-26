#!/bin/bash
# Qwen-Image-2.1 environment on AutoDL.
#   source /root/qwen-image-2.1/qwen_env.sh
export PATH=/root/miniconda3/bin:$PATH
export QWEN_ROOT=/root/qwen-image-2.1
export QWEN_MODEL_DIR=${QWEN_MODEL_DIR:-/root/autodl-tmp/Qwen-Image-2.1}
export HF_HOME=${HF_HOME:-/root/autodl-tmp/hf}
export MODELSCOPE_CACHE=${MODELSCOPE_CACHE:-/root/autodl-tmp/modelscope}
export HF_HUB_ENABLE_HF_TRANSFER=${HF_HUB_ENABLE_HF_TRANSFER:-0}
# 学术加速: GitHub / HuggingFace。注释掉可避免走代理访问国内源。
if [ -f /etc/network_turbo ]; then source /etc/network_turbo >/dev/null 2>&1; fi
export no_proxy="localhost,127.0.0.1,modelscope.com,aliyuncs.com,tencentyun.com,wisemodel.cn,mirrors.aliyun.com"
# 48G 单卡（魔改 4090 / AD102 sm_89）：全 BF16 常驻，33.1G 权重 + 2K 激活刚好塞得下
export QWEN_MODE=${QWEN_MODE:-auto}       # auto | real | mock
export QWEN_OFFLOAD=${QWEN_OFFLOAD:-none} # none=全常驻显存；OOM 时改 model
export QWEN_TORCH_DTYPE=${QWEN_TORCH_DTYPE:-bfloat16}
export QWEN_PRELOAD=${QWEN_PRELOAD:-1}    # 启动即加载，避免首请求等 2~3 分钟
export QWEN_TILE_VAE=${QWEN_TILE_VAE:-0}
export QWEN_PORT=${QWEN_PORT:-6006}
