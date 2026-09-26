export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
cd /root/qwen-image-2.1
pkill -f 'service/server.py' 2>/dev/null; sleep 1
QWEN_MODE=mock nohup python service/server.py > logs/service_mock.log 2>&1 &
sleep 8
python - <<'PY'
import base64, io, json, time
import requests
from PIL import Image

B = "http://127.0.0.1:6006"
def show(name, r):
    ok = r.status_code < 400
    print(f"[{'OK ' if ok else 'ERR'}] {name} -> {r.status_code}")
    return r

h = show("GET /health", requests.get(B + "/health", timeout=20)).json()
print("   mode=%s mock=%s ckpt=%s" % (h["mode"], h["mock"], h["checkpoint"]["present"]))
show("GET /v1/models", requests.get(B + "/v1/models", timeout=20))

r = show("POST /v1/images/generations", requests.post(B + "/v1/images/generations", json={
    "prompt": "smoke", "width": 256, "height": 256, "num_inference_steps": 4, "seed": 7}, timeout=60)).json()
print("   data keys:", sorted(r["data"][0].keys()), "size:", r["size"])
img = Image.open(io.BytesIO(base64.b64decode(r["data"][0]["b64_json"])))
print("   decoded image:", img.size, img.mode)

buf = io.BytesIO(); Image.new("RGB", (300, 200), (10, 200, 90)).save(buf, "PNG"); buf.seek(0)
r = show("POST /v1/images/edits", requests.post(B + "/v1/images/edits",
    data={"prompt": "make it blue", "num_inference_steps": "4"},
    files=[("image", ("in.png", buf.getvalue(), "image/png"))], timeout=60)).json()
print("   edit size:", r["size"])

j = show("POST /v1/jobs", requests.post(B + "/v1/jobs", json={"prompt": "async", "width": 256, "height": 256}, timeout=30)).json()
print("   job id:", j["id"])
for _ in range(20):
    time.sleep(1)
    g = requests.get(B + "/v1/jobs/" + j["id"], timeout=20).json()
    if g["status"] in ("succeeded", "failed"):
        break
print("   job status:", g["status"], "has result:", bool(g.get("result")))
show("DELETE /v1/jobs", requests.delete(B + "/v1/jobs/" + j["id"], timeout=20))
show("GET /openapi.json", requests.get(B + "/openapi.json", timeout=20))
print("paths:", sorted(requests.get(B + "/openapi.json", timeout=20).json()["paths"].keys()))

r = requests.post(B + "/v1/images/generations", json={"prompt": ""}, timeout=20)
print("[OK ] empty prompt rejected ->", r.status_code)
PY
echo '--- server log ---'
grep -E 'Traceback|Error|ERROR' logs/service_mock.log | head -5
tail -3 logs/service_mock.log
pkill -f 'service/server.py'
