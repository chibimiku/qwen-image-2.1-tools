export PATH=/root/miniconda3/bin:$PATH
for i in $(seq 1 30); do
  H=$(curl -s -m 5 localhost:6006/health 2>/dev/null)
  case "$H" in
    *'"loaded":true'*) echo "READY after ${i} polls"; echo "$H"; break;;
  esac
  sleep 5
done
echo "--- smoke 512 ---"
python - <<'PY'
import base64, time, requests
t0=time.time()
r=requests.post("http://127.0.0.1:6006/v1/images/generations",json={
  "prompt":"a cute cat sitting by a river","width":512,"height":512,
  "num_inference_steps":8,"seed":1},timeout=900)
print("http", r.status_code, f"{time.time()-t0:.1f}s")
if r.status_code==200:
    raw=base64.b64decode(r.json()["data"][0]["b64_json"])
    open("/root/qwen-image-2.1/outputs/smoke_512.png","wb").write(raw)
    print("saved", len(raw), "bytes")
else:
    print(r.text[:400])
PY
echo "--- vram after smoke ---"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
curl -s -m 5 localhost:6006/health
