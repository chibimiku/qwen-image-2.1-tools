export PATH=/root/miniconda3/bin:$PATH
echo "=== service log ==="
tail -6 /root/qwen-image-2.1/logs/service.log
echo "=== health ==="
curl -s -m 8 localhost:6006/health || echo SERVICE_DOWN
echo
echo "=== vram ==="
nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader
echo "=== proc ==="
pgrep -af 'service/server.py' | grep -v pgrep || echo 'not running'
