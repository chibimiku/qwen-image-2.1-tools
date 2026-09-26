#!/bin/bash
# Polls until the checkpoint is complete (or timeout), reporting progress.
export PATH=/root/miniconda3/bin:$PATH
R=/root/qwen-image-2.1
DIR=/root/autodl-tmp/Qwen-Image-2.1
TARGET_MB=33135
echo "[monitor] $(date '+%F %T') start"
while true; do
  LEFT=$(find "$DIR" -name '*.incomplete' 2>/dev/null | wc -l)
  MB=$(du -sm "$DIR" 2>/dev/null | cut -f1)
  PCT=$(( MB * 100 / TARGET_MB ))
  RUN=$(pgrep -cf snapshot_download || true)
  echo "[monitor] $(date '+%H:%M:%S') ${MB}MB / ${TARGET_MB}MB (${PCT}%) incomplete=${LEFT} downloader=${RUN}"
  if [ "$LEFT" -eq 0 ] && [ -f "$DIR/model_index.json" ] && [ -f "$DIR/transformer/diffusion_pytorch_model.safetensors.index.json" ]; then
    echo "[monitor] CHECKPOINT_COMPLETE ${MB}MB"
    break
  fi
  if [ "$RUN" -eq 0 ] && [ "$LEFT" -gt 0 ]; then
    echo "[monitor] downloader died with ${LEFT} files unfinished -> restarting"
    cd "$R" && nohup python -c "
from modelscope import snapshot_download
snapshot_download('Qwen/Qwen-Image-2.1', local_dir='$DIR', max_workers=16)
print('DOWNLOAD_DONE')
" >> "$R/logs/download3.log" 2>&1 &
  fi
  sleep 60
done
echo "[monitor] $(date '+%F %T') finished"
