export PATH=/root/miniconda3/bin:$PATH
DIR=/root/autodl-tmp/Qwen-Image-2.1
TARGET_MB=33135
DEADLINE=$(( $(date +%s) + 2700 ))
prev=$(du -sm $DIR | cut -f1)
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  sleep 120
  now=$(du -sm $DIR | cut -f1)
  left=$(find $DIR -name '*.incomplete' | wc -l)
  rate=$(( (now - prev) / 2 ))
  echo "$(date '+%H:%M:%S') ${now}MB/33135MB left_files=${left} rate=${rate}MB/min"
  prev=$now
  if [ "$left" -eq 0 ]; then
    echo "CHECKPOINT_COMPLETE total=${now}MB"
    find $DIR -name '*.safetensors' -printf '%10s %p\n'
    exit 0
  fi
done
echo "MONITOR_TIMEOUT left_files=$(find $DIR -name '*.incomplete' | wc -l) size=$(du -sm $DIR | cut -f1)MB"
find $DIR -name '*.incomplete' -printf '%10s %p\n'
