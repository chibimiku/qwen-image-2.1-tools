export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
cd /root/qwen-image-2.1
echo "=== restart service with the tuned defaults ==="
pkill -f 'service/server.py' 2>/dev/null; sleep 2
QWEN_TILE_VAE=1 PATH=/root/miniconda3/bin:$PATH bash scripts/serve.sh start
sleep 10
pgrep -af 'service/server.py' | grep -v pgrep
echo "=== log ==="
tail -4 logs/service.log
