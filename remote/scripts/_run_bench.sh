export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
echo "=== stop service to free the whole 47G card for the bench ==="
pkill -f 'service/server.py' 2>/dev/null; sleep 3
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
echo "=== bench: 1024/20 + 2048/40 ==="
cd /root/qwen-image-2.1
python scripts/bench.py 2>&1 | grep -vE '^\s*$|it/s\]|Loading'
echo "=== outputs ==="
ls -la outputs/
echo "=== restarting service ==="
nohup python service/server.py > logs/service.log 2>&1 &
echo $! > service.pid
echo "pid=$(cat service.pid)"
