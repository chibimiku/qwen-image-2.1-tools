export PATH=/root/miniconda3/bin:$PATH
echo '=== download status ==='
du -sh /root/autodl-tmp/Qwen-Image-2.1
tail -c 300 /root/qwen-image-2.1/logs/download2.log | tr '\r' '\n' | tail -3
grep -c DOWNLOAD_DONE /root/qwen-image-2.1/logs/download2.log || true
echo '=== remaining unfinished ==='
find /root/autodl-tmp/Qwen-Image-2.1 -name '*.incomplete' | wc -l
