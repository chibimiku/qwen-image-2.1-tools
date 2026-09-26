export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
cd /root/qwen-image-2.1
pkill -f 'service/server.py' 2>/dev/null; sleep 1
python -c "
import inspect
from diffusers import DiffusionPipeline
print('from_pretrained supports dtype:', 'dtype' in inspect.signature(DiffusionPipeline.from_pretrained).parameters)
"
nohup python service/server.py > logs/service.log 2>&1 &
echo $! > service.pid
sleep 8
echo '--- health ---'
curl -s -m 10 localhost:6006/health
echo
echo '--- endpoints ---'
python - <<'PY'
import base64, io, requests
from PIL import Image
B="http://127.0.0.1:6006"
r=requests.post(B+"/v1/images/generations",json={"prompt":"post-download check","width":256,"height":256,"num_inference_steps":4},timeout=60)
print("t2i:", r.status_code, "bytes:", len(base64.b64decode(r.json()["data"][0]["b64_json"])))
PY
echo '--- log warnings ---'
grep -icE 'futurewarning|deprecat' logs/service.log || true
tail -3 logs/service.log
