export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
pip install -q modelscope 2>&1 | tail -2
python -c "import modelscope;print('modelscope', modelscope.__version__)"
nohup python - <<'PY' > /root/qwen-image-2.1/logs/download.log 2>&1 &
from modelscope import snapshot_download
p = snapshot_download('Qwen/Qwen-Image-2.1', local_dir='/root/autodl-tmp/Qwen-Image-2.1')
print('DOWNLOAD_DONE', p)
PY
echo "download pid=$!"
sleep 25
echo '--- log ---'
tail -15 /root/qwen-image-2.1/logs/download.log
echo '--- data disk ---'
df -h /root/autodl-tmp | tail -1
du -sh /root/autodl-tmp/Qwen-Image-2.1 2>/dev/null || true
