#!/bin/bash
# 一次性环境恢复脚本（换机 / 重置后跑一遍即可）。
#   bash /root/qwen-image-2.1/scripts/bootstrap.sh
set -u
export PATH=/root/miniconda3/bin:$PATH
R=/root/qwen-image-2.1
mkdir -p $R/{service,scripts,logs,outputs}

echo "== 1/5 依赖 =="
source /etc/network_turbo >/dev/null 2>&1
pip install -q -U "transformers>=5.17" accelerate safetensors hf_transfer sentencepiece pillow \
    fastapi "uvicorn[standard]" python-multipart requests modelscope 2>&1 | tail -2
python -c "import importlib;[print(m, getattr(importlib.import_module(m),'__version__','?')) for m in ['torch','transformers','diffusers','fastapi']]"
python -c "from diffusers import QwenImage21Pipeline; print('QwenImage21Pipeline OK')"

echo "== 2/5 权重 =="
if [ -f $R/../autodl-tmp/Qwen-Image-2.1/model_index.json ] && [ -z "$(find /root/autodl-tmp/Qwen-Image-2.1 -name '*.incomplete' | head -1)" ]; then
  echo "checkpoint OK"
else
  bash $R/scripts/download_model.sh ms
fi

echo "== 3/5 启动服务 =="
bash $R/scripts/serve.sh start
sleep 5
curl -s -m 5 localhost:6006/health | head -c 400; echo

echo "== 4/5 端口提示 =="
echo "自定义服务地址（控制台复制）: https://<实例ID>-<hash>.seetacloud.com:8443"
echo "隧道: ssh -p <端口> -L 16006:127.0.0.1:6006 root@<实例域名> -N"

echo "== 5/5 完成 =="
