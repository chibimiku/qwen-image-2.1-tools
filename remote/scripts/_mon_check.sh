export PATH=/root/miniconda3/bin:$PATH
echo '=== monitor proc ==='; pgrep -af watch_download.sh | grep -v pgrep
echo '=== monitor log ==='; tail -5 /root/qwen-image-2.1/logs/monitor.log
echo '=== downloader proc ==='; pgrep -af snapshot_download | grep -v pgrep | head -2
echo '=== sizes ==='; du -sm /root/autodl-tmp/Qwen-Image-2.1 | cut -f1
find /root/autodl-tmp/Qwen-Image-2.1 -name '*.incomplete' -printf '%10s %f\n'
echo '=== 60s delta ==='
A=$(du -sm /root/autodl-tmp/Qwen-Image-2.1 | cut -f1); sleep 60
B=$(du -sm /root/autodl-tmp/Qwen-Image-2.1 | cut -f1)
echo "delta=$((B-A))MB/min  now=${B}MB  left=$((33135-B))MB  ETA=$(( (33135-B)/((B-A)/1+1) ))min"
