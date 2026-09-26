export PATH=/root/miniconda3/bin:$PATH
A=$(du -sm /root/autodl-tmp/Qwen-Image-2.1 2>/dev/null | cut -f1)
sleep 30
B=$(du -sm /root/autodl-tmp/Qwen-Image-2.1 2>/dev/null | cut -f1)
echo "before=${A}MB after=${B}MB delta=$((B-A))MB in 30s => $(( (B-A)/30 )) MB/s"
echo "remaining ~ $(( 33135 - B )) MB"
if [ $((B-A)) -gt 0 ]; then echo "ETA ~ $(( (33135-B) / ((B-A)/30+1) / 60 )) min"; fi
echo '=== downloaders ==='
pgrep -af 'snapshot_download|python -$|python - ' | grep -v pgrep | head
echo '=== log ==='
tail -c 300 /root/qwen-image-2.1/logs/download.log | tr '\r' '\n' | tail -4
