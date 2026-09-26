#!/bin/bash
# Download the Qwen-Image-2.1 checkpoint. Default route: ModelScope (no proxy).
# Usage: bash /root/qwen-image-2.1/scripts/download_model.sh [hf]
set -e
source /root/qwen-image-2.1/qwen_env.sh
ROUTE=${1:-ms}
DEST="$QWEN_MODEL_DIR"
mkdir -p "$DEST" /root/qwen-image-2.1/logs
LOG=/root/qwen-image-2.1/logs/download.log

if [ "$ROUTE" = "hf" ]; then
  echo "[dl] route=huggingface (proxy) -> $DEST"
  python -m pip install -q "huggingface_hub[cli]"
  nohup huggingface-cli download Qwen/Qwen-Image-2.1 --local-dir "$DEST" \
      > "$LOG" 2>&1 &
else
  echo "[dl] route=modelscope -> $DEST"
  python -m pip install -q modelscope
  nohup python -c "
from modelscope import snapshot_download
p = snapshot_download('Qwen/Qwen-Image-2.1', local_dir='$DEST')
print('DONE', p)
" > "$LOG" 2>&1 &
fi
echo "[dl] pid=$! log=$LOG"
sleep 20
tail -5 "$LOG" || true
