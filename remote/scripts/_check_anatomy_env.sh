#!/bin/bash
# 查审图模型到底有没有落地、以及当前判定是否可用
set -u
echo "=== 1. 本地有没有 SmolVLM ==="
for d in /root/autodl-tmp/modelscope/hub /root/.cache/huggingface/hub \
         /root/autodl-tmp/hf/hub /root/autodl-tmp/hf; do
  [ -d "$d" ] && find "$d" -maxdepth 3 -iname '*SmolVLM*' 2>/dev/null | head -5
done
find /root /autodl-fs -maxdepth 7 -iname '*SmolVLM*' -type d 2>/dev/null | head -8
echo "(以上为空 = 没下载下来)"

echo
echo "=== 2. 网络环境 ==="
[ -f /etc/network_turbo ] && echo "有 /etc/network_turbo（学术加速）" || echo "无 network_turbo"
echo "HF 可达性："
timeout 8 curl -s -o /dev/null -w '  huggingface.co -> %{http_code}\n' https://huggingface.co 2>/dev/null || echo "  huggingface.co -> 不可达"
timeout 8 curl -s -o /dev/null -w '  modelscope.cn  -> %{http_code}\n' https://www.modelscope.cn 2>/dev/null || echo "  modelscope.cn  -> 不可达"

echo
echo "=== 3. 服务里的审图状态 ==="
curl -s -m 8 localhost:6006/health | /root/miniconda3/bin/python -c "
import sys, json
h = json.load(sys.stdin)
print('  anatomy_checker:', json.dumps(h.get('anatomy_checker'), ensure_ascii=False))
"

echo
echo "=== 4. qwen_env.sh 里的审图配置 ==="
grep -i anatomy /root/qwen-image-2.1/qwen_env.sh 2>/dev/null || echo "(qwen_env.sh 里没配)"
