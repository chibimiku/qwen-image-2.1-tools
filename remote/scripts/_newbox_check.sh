#!/bin/bash
# 新实例环境盘点：权重 / 服务 / 审图模型 / 依赖
set -u
R=/root/qwen-image-2.1
echo "=== 1. 权重完整性 ==="
ls "$R/../autodl-tmp/Qwen-Image-2.1" 2>/dev/null | tr '\n' ' '; echo
ls /root/autodl-tmp/Qwen-Image-2.1/ | tr '\n' ' '; echo
n=$(find /root/autodl-tmp/Qwen-Image-2.1 -name '*.incomplete' 2>/dev/null | wc -l)
echo "  incomplete 文件数: $n  （0 = 下完了）"
du -sh /root/autodl-tmp/Qwen-Image-2.1 2>/dev/null

echo
echo "=== 2. 服务状态 ==="
curl -s -m 5 localhost:6006/health | head -c 200 || echo "  服务没起"
echo

echo
echo "=== 3. 审图模型 ==="
ls -d /root/autodl-tmp/models/SmolVLM* 2>/dev/null || echo "  /root/autodl-tmp/models 下没有"
ls -d /root/autodl-tmp/hf/hub/models--*SmolVLM* 2>/dev/null || echo "  HF 缓存里没有"

echo
echo "=== 4. python 依赖 ==="
PY=/root/miniconda3/bin/python
[ -x "$PY" ] || PY=python3
$PY - <<'PY'
mods = ["torch", "diffusers", "transformers", "fastapi", "PIL", "accelerate"]
for m in mods:
    try:
        mod = __import__(m)
        print(f"  {m:14} {getattr(mod, '__version__', '?' )}")
    except Exception as e:
        print(f"  {m:14} 缺失（{type(e).__name__}）")
try:
    from diffusers import QwenImage21Pipeline
    print("  QwenImage21Pipeline 可用 ✅")
except Exception as e:
    print(f"  QwenImage21Pipeline 不可用：{e}")
PY

echo
echo "=== 5. repo 内容 ==="
ls "$R" | tr '\n' ' '; echo
ls "$R/service" 2>/dev/null | tr '\n' ' '; echo
