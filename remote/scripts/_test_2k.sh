export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
cd /root/qwen-image-2.1
pkill -f 'service/server.py' 2>/dev/null; sleep 3
export QWEN_TILE_VAE=1
nohup python service/server.py > logs/service.log 2>&1 &
echo $! > service.pid
echo "service pid=$(cat service.pid)  QWEN_TILE_VAE=$QWEN_TILE_VAE"
for i in $(seq 1 40); do
  H=$(curl -s -m 5 localhost:6006/health 2>/dev/null)
  case "$H" in *'"loaded":true'*) echo "READY"; break;; esac
  sleep 5
done
echo "=== 2048x2048 / 40 steps with tiled VAE ==="
python - <<'PY'
import base64, time, requests
t0=time.time()
r=requests.post("http://127.0.0.1:6006/v1/images/generations", json={
  "prompt": "A panoramic mountain landscape at dawn, layered mist, a calm lake reflecting "
            "pink clouds, pine forest silhouette, ultra detailed, cinematic",
  "width": 2048, "height": 2048, "num_inference_steps": 40, "seed": 7}, timeout=3600)
dt=time.time()-t0
print("http", r.status_code, f"{dt:.1f}s")
if r.status_code==200:
    raw=base64.b64decode(r.json()["data"][0]["b64_json"])
    open("/root/qwen-image-2.1/outputs/t2i_2048_40steps.png","wb").write(raw)
    print("saved", len(raw), "bytes")
else:
    print(r.text[:600])
PY
echo "=== health after 2K ==="
curl -s -m 5 localhost:6006/health
echo
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
