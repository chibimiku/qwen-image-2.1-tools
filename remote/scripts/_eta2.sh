export PATH=/root/miniconda3/bin:$PATH
A=$(du -sm /root/autodl-tmp/Qwen-Image-2.1 | cut -f1); sleep 45
B=$(du -sm /root/autodl-tmp/Qwen-Image-2.1 | cut -f1)
echo "start=${A}MB now=${B}MB delta=$((B-A))MB/45s => $(( (B-A)/45 )) MB/s"
echo "ETA ~ $(( (33135-B) / ((B-A)/45 + 1) / 60 )) min (if steady)"
echo '=== per-file ==='
find /root/autodl-tmp/Qwen-Image-2.1 -name '*.safetensors*' -printf '%10s  %f\n' | sort -k2
echo '=== log tail ==='
tail -c 400 /root/qwen-image-2.1/logs/download2.log | tr '\r' '\n' | tail -6
