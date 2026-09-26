export PATH=/root/miniconda3/bin:$PATH
echo '=== kill all downloaders ==='
pkill -f 'snapshot_download' ; pkill -f 'from modelscope' ; pkill -9 -f 'python -$' 2>/dev/null
sleep 2
pgrep -af python | grep -v pgrep | head
echo '=== on-disk truth ==='
find /root/autodl-tmp/Qwen-Image-2.1 -name '*.safetensors*' -printf '%10s  %p\n' 2>/dev/null | sort -k2
echo '=== total ==='
du -sh /root/autodl-tmp/Qwen-Image-2.1
echo '=== restart: 16 workers, sequential=False ==='
nohup python -c "
from modelscope import snapshot_download
p = snapshot_download('Qwen/Qwen-Image-2.1', local_dir='/root/autodl-tmp/Qwen-Image-2.1', max_workers=16)
print('DOWNLOAD_DONE', p)
" > /root/qwen-image-2.1/logs/download2.log 2>&1 &
echo "pid=$!"
