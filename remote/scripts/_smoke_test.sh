export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
echo '=== start mock service for contract smoke test ==='
pkill -f 'service/server.py' 2>/dev/null; sleep 1
cd /root/qwen-image-2.1
QWEN_MODE=mock nohup python service/server.py > logs/service_mock.log 2>&1 &
echo "pid=$!"
sleep 8
echo '--- health ---'
curl -s -m 10 localhost:6006/health
echo
echo '--- t2i ---'
curl -s -m 30 -X POST localhost:6006/v1/images/generations -H 'Content-Type: application/json' \
  -d '{"prompt":"smoke test","width":256,"height":256,"num_inference_steps":4}' \
  | python -c "import sys,json;d=json.load(sys.stdin);print('keys:',list(d.keys()));print('data0:',{k:(str(v)[:40]+'...' if k=='b64_json' else v) for k,v in d['data'][0].items()})"
echo '--- edit (synthetic png) ---'
python -c "from PIL import Image; Image.new('RGB',(256,256),(120,30,200)).save('/tmp/in.png')"
curl -s -m 30 -X POST localhost:6006/v1/images/edits -F 'prompt=make it blue' -F 'image=@/tmp/in.png' \
  | python -c "import sys,json;d=json.load(sys.stdin);print('ok', d['size'], len(d['data']))"
echo '--- job ---'
JID=$(curl -s -m 30 -X POST localhost:6006/v1/jobs -H 'Content-Type: application/json' -d '{"prompt":"async test","width":256,"height":256}' | python -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "job=$JID"; sleep 3
curl -s -m 30 "localhost:6006/v1/jobs/$JID" | python -c "import sys,json;d=json.load(sys.stdin);print('status',d['status'],'has_result',bool(d.get('result')))"
echo '--- stop mock ---'
bash scripts/serve.sh stop 2>/dev/null; pkill -f 'service/server.py'; sleep 1
tail -6 logs/service_mock.log
