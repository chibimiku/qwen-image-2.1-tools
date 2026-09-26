export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
cd /root/qwen-image-2.1
pkill -f 'service/server.py' 2>/dev/null; sleep 1
echo '=== real mode without GPU (expect 409) ==='
QWEN_MODE=real nohup python service/server.py > logs/service_real.log 2>&1 &
sleep 8
curl -s -m 10 localhost:6006/health | python -c "import sys,json;h=json.load(sys.stdin);print('mode=%s mock=%s gpu=%s'%(h['mode'],h['mock'],h['gpu']['available']))"
curl -s -o /tmp/r.json -w 't2i http=%{http_code} ' -m 30 -X POST localhost:6006/v1/images/generations -H 'Content-Type: application/json' -d '{"prompt":"x","width":64,"height":64}'
cat /tmp/r.json; echo
echo '=== stop ==='
pkill -f 'service/server.py'; sleep 1
echo '=== AUTO mode: what would happen now ==='
python - <<'PY'
import os, torch
print('cuda available:', torch.cuda.is_available())
print('QWEN_MODE env:', os.environ.get('QWEN_MODE', 'auto (default)'))
PY
