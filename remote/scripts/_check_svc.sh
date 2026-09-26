export PATH=/root/miniconda3/bin:$PATH
echo '=== 进程 ==='
pgrep -af 'service/server.py' | grep -v pgrep || echo 'not running'
echo '=== 日志尾部 ==='
tail -30 /root/qwen-image-2.1/logs/service.log
echo '=== 日志里的报错 ==='
grep -nE 'Error|Traceback|error|Exception' /root/qwen-image-2.1/logs/service.log | tail -15
echo '=== health ==='
curl -s -m 8 localhost:6006/health || echo 'SERVICE_DOWN'
echo
echo '=== GPU ==='
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
