#!/bin/bash
# 新实例上的部署收尾：设 key + tile_vae，重启服务
set -u
R=/root/qwen-image-2.1
ENVF=$R/qwen_env.sh
KEY="${KEY:?KEY 未注入}"

# 关键项写进环境脚本（幂等：先删旧的同名行再加）
cp -n "$ENVF" "$ENVF.orig" 2>/dev/null || true
sed -i '/^export QWEN_API_KEY=/d;/^export QWEN_API_KEYS=/d;/^export QWEN_TILE_VAE=/d;/^export QWEN_ANATOMY_MODEL=/d' "$ENVF"
{
  echo "export QWEN_API_KEY=${KEY}"
  echo "export QWEN_API_KEYS=1730"
  echo "export QWEN_TILE_VAE=1"
  echo "export QWEN_ANATOMY_MODEL=/root/autodl-tmp/models/SmolVLM2-2.2B-Instruct"
  echo "export QWEN_ANATOMY_DEVICE=cpu"
} >> "$ENVF"

echo "=== qwen_env.sh 尾部 ==="
tail -5 "$ENVF"
echo
echo "=== 启动服务 ==="
cd $R && bash scripts/serve.sh restart 2>&1 | tail -6
