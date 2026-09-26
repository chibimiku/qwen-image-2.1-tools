export PATH=/root/miniconda3/bin:$PATH
DIR=/root/autodl-tmp/Qwen-Image-2.1
echo '=== size / unfinished ==='
du -sh $DIR; find $DIR -name '*.incomplete' | wc -l
echo '=== monitor log tail ==='
tail -6 /root/qwen-image-2.1/logs/monitor.log
echo '=== downloader alive? ==='
pgrep -af snapshot_download | grep -v pgrep | head -3
echo '=== completed shards ==='
find $DIR -name '*.safetensors' -printf '%10s %p\n'
echo '=== nvcc / compute ==='
ls /usr/local/ | grep -i cuda; nvcc --version 2>/dev/null | tail -2 || echo 'no nvcc in PATH'
