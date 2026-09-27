#!/bin/bash
# 下载人体异常复检用的小模型（可选功能：请求里 anatomy_check=true 才会加载）。
#   bash /root/qwen-image-2.1/scripts/download_anatomy_model.sh [目标目录]
#
# 为什么走 ModelScope：2026-09-26 在同一台实例上实测同一个分片
#   HF 直连（学术加速） 0.21 MB/s   hf-mirror 1.9 MB/s   ModelScope 9.5 MB/s
# 8.6 GB 的 2.2B 权重走 ModelScope 约 15 分钟，走 HF 要一个多小时还会中途卡死。
set -u
export PATH=/root/miniconda3/bin:$PATH
REPO=${QWEN_ANATOMY_REPO:-HuggingFaceTB/SmolVLM2-2.2B-Instruct}
DEST=${1:-/root/autodl-tmp/models/SmolVLM2-2.2B-Instruct}

echo "模型仓库 : $REPO"
echo "目标目录 : $DEST"
echo "磁盘可用 : $(df -h "$(dirname "$DEST")" | tail -1 | awk '{print $4}')"
mkdir -p "$DEST"

if [ -f "$DEST/model.safetensors.index.json" ] && [ -z "$(find "$DEST" -name '*.tmp' -o -name '*.part' | head -1)" ]; then
  echo "看起来已经下好了：$(du -sh "$DEST" | cut -f1)"
else
  for i in 1 2 3 4 5; do
    echo "--- 第 $i 轮 $(date '+%T') 当前 $(du -sh "$DEST" 2>/dev/null | cut -f1) ---"
    modelscope download --model "$REPO" --local_dir "$DEST" && break
    echo "--- 第 $i 轮失败，5 秒后重试（已下的分片会续传）---"
    sleep 5
  done
fi

echo
echo "=== 完整性核对（对着 ModelScope 的文件清单逐个比大小）==="
python - "$REPO" "$DEST" <<'PY'
import json, os, sys, urllib.request
repo, dest = sys.argv[1], sys.argv[2]
url = (f"https://www.modelscope.cn/api/v1/models/{repo}/repo/files?Revision=master&Recursive=true")
try:
    files = json.loads(urllib.request.urlopen(url, timeout=25).read()).get("Data", {}).get("Files", [])
except Exception as exc:                                    # noqa: BLE001
    print("  拿不到官方清单，跳过核对：", exc); sys.exit(0)
bad = 0
for f in files:
    p = os.path.join(dest, f.get("Path", ""))
    if not os.path.exists(p):
        print("  缺  ", f.get("Path")); bad += 1
    elif os.path.getsize(p) != (f.get("Size") or 0):
        print("  不符", f.get("Path")); bad += 1
print(f"  {len(files)} 个文件，异常 {bad} 个" + ("（与官方一致）" if not bad else ""))
PY

echo
echo "=== 让服务用上它（写进 qwen_env.sh，别覆盖整个文件 —— 里面有真 key）==="
cat <<EOF
  export QWEN_ANATOMY_MODEL=$DEST
  export QWEN_ANATOMY_DEVICE=cpu
  export QWEN_ANATOMY_DTYPE=auto          # 支持 bf16 的 CPU 会用它，快 ~1.8 倍
  export QWEN_ANATOMY_MIN_CONFIDENCE=0.78
  改完重启：bash /root/qwen-image-2.1/scripts/serve.sh restart
  依赖提醒：SmolVLM2 的 processor 需要 num2words（bootstrap.sh 已带上）
EOF

echo
echo "=== 自检 ==="
python - <<PY
import time, torch
from transformers import AutoProcessor, AutoModelForImageTextToText
t0 = time.time()
proc = AutoProcessor.from_pretrained("$DEST")
model = AutoModelForImageTextToText.from_pretrained(
    "$DEST", dtype=torch.bfloat16, low_cpu_mem_usage=True).to("cpu").eval()
print("  加载成功 %.1fs，参数量 %.0fM，dtype=%s" % (
    time.time() - t0, sum(p.numel() for p in model.parameters()) / 1e6,
    next(model.parameters()).dtype))
PY
