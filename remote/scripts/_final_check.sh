export PATH=/root/miniconda3/bin:$PATH
DIR=/root/autodl-tmp/Qwen-Image-2.1
echo "=== $(date '+%F %T') ==="
echo '--- unfinished files ---'
find $DIR -name '*.incomplete' | wc -l
find $DIR -name '*.incomplete' -printf '%10s %f\n'
echo '--- finished shards ---'
find $DIR -name '*.safetensors' -printf '%10s %p\n'
echo '--- total size vs expected 33135 MB ---'
du -sm $DIR | cut -f1
echo '--- downloader alive? ---'
pgrep -af snapshot_download | grep -v pgrep | head -2 || echo 'downloader exited'
echo '--- DOWNLOAD_DONE marker ---'
grep -h DOWNLOAD_DONE /root/qwen-image-2.1/logs/download*.log 2>/dev/null | tail -2
echo '--- monitor log tail ---'
tail -4 /root/qwen-image-2.1/logs/monitor.log
echo '--- disk ---'
df -h / /root/autodl-tmp | sed -n '1,4p'
echo '--- key json files ---'
for f in model_index.json transformer/diffusion_pytorch_model.safetensors.index.json text_encoder/model.safetensors.index.json vae/config.json scheduler/scheduler_config.json processor/tokenizer.json; do
  if [ -f "$DIR/$f" ]; then echo "OK   $f  $(stat -c%s $DIR/$f) bytes"; else echo "MISS $f"; fi
done
