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
# 分块 VAE 解码：**2048² 出图必须开**，否则崩在 VAE 上采样层
# （实测：不开时 2048² 文生图直接 CUDA OOM；开了之后峰值 32.5G、115s 出图）
export QWEN_TILE_VAE=${QWEN_TILE_VAE:-1}
export QWEN_PORT=${QWEN_PORT:-6006}
# ── 可选的人体异常复检 ────────────────────────────────────────────────────
# 只有请求 anatomy_check=true 时才按需加载；默认放 CPU，完全不占主模型显存。
# 500M 那版答不出 `PASS|置信度|理由` 的格式（永远只回 "PASS."），已换 2.2B。
# 实例上从 ModelScope 下到本地目录后，直接指过去可省掉首次联网下载：
#   export QWEN_ANATOMY_MODEL=/root/autodl-tmp/models/SmolVLM2-2.2B-Instruct
export QWEN_ANATOMY_MODEL=${QWEN_ANATOMY_MODEL:-HuggingFaceTB/SmolVLM2-2.2B-Instruct}
export QWEN_ANATOMY_DEVICE=${QWEN_ANATOMY_DEVICE:-cpu}
# CPU 上的精度：auto = 支持 bf16 就用 bf16（本机实测快 1.8 倍）；老 CPU 显式设 float32
export QWEN_ANATOMY_DTYPE=${QWEN_ANATOMY_DTYPE:-auto}
export QWEN_ANATOMY_MIN_CONFIDENCE=${QWEN_ANATOMY_MIN_CONFIDENCE:-0.78}
# ── 接口鉴权 ─────────────────────────────────────────────────────────────
# QWEN_API_KEY : 主 key（访问 /v1/* 与 /docs 需要它）
#                带法一 Authorization: Bearer <key>   带法二 ?key=<key>
#                带法三 浏览器登录后拿到的 HttpOnly Cookie 会话（推荐：key 不落页面、不存本地）
#                /health 与控制台首页不受保护（否则存活探测和打开页面都做不了）
# QWEN_API_KEYS: 额外 key，逗号分隔，**同样有效**
#                用途：换 key 时给旧的留个过渡期；或给自己人一个短口令、对外用长随机串
# QWEN_UI_KEY  : 控制台是否把 key 填进"直连排障"输入框
#                inject = 填（只有自己用）/ auto = 不填，走登录（默认）/ off = 不注入
# ⚠️ 下面的 key 是占位符，部署时改成自己的（实例上的那份已经是真值）
export QWEN_API_KEY=${QWEN_API_KEY:-CHANGE_ME}
export QWEN_API_KEYS=${QWEN_API_KEYS:-}
export QWEN_UI_KEY=${QWEN_UI_KEY:-auto}
