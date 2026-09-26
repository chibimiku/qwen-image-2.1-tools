export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
echo "=== checkpoint ==="
du -sh /root/autodl-tmp/Qwen-Image-2.1; find /root/autodl-tmp/Qwen-Image-2.1 -name '*.incomplete' | wc -l
echo "=== old proc ==="
pgrep -af 'service/server.py' | grep -v pgrep || echo 'none running'
echo "=== torch/cuda ==="
python -c "import torch;print(torch.__version__, torch.version.cuda, torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '-')"
echo "=== restart service (preload on, real cuda) ==="
cd /root/qwen-image-2.1
pkill -f 'service/server.py' 2>/dev/null; sleep 1
nohup python service/server.py > logs/service.log 2>&1 &
echo $! > service.pid
echo "pid=$(cat service.pid)"
