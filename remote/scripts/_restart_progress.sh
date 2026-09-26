export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
cd /root/qwen-image-2.1
pkill -f 'service/server.py' 2>/dev/null; sleep 3
nohup python service/server.py > logs/service.log 2>&1 &
echo $! > service.pid
for i in $(seq 1 40); do
  H=$(curl -s -m 5 localhost:6006/health 2>/dev/null)
  case "$H" in *'"loaded":true'*) echo "READY"; break;; esac
  sleep 5
done
echo
echo '=== 后端：进度回调是否真的在跑 ==='
python - <<'PY'
import json, threading, time, urllib.request

BASE = "http://127.0.0.1:6006"
KEY = {"Authorization": "Bearer 1730", "Content-Type": "application/json"}

def get(path):
    r = urllib.request.Request(BASE + path, headers={"Authorization": "Bearer 1730"})
    return json.loads(urllib.request.urlopen(r, timeout=20).read())

# 后台发一个 20 步的请求
def fire():
    body = json.dumps({"prompt": "a lighthouse in a storm, dramatic clouds",
                       "width": 1024, "height": 1024, "num_inference_steps": 20,
                       "seed": 5, "request_id": "probe_progress_1"}).encode()
    r = urllib.request.Request(BASE + "/v1/images/generations", data=body, headers=KEY)
    global RESULT
    RESULT = json.loads(urllib.request.urlopen(r, timeout=600).read())

RESULT = None
t = threading.Thread(target=fire, daemon=True); t.start()

seen = []
t0 = time.time()
while time.time() - t0 < 240:
    try:
        p = get("/v1/progress/probe_progress_1")
        snap = (p["status"], p["steps_done"], p["total"], p["pct"], p["per_step_s"], p["eta_s"])
        if not seen or seen[-1] != snap:
            seen.append(snap)
            print(f"  {p['status']:8s} {p['steps_done']:3d}/{p['total']:<3d} {p['pct']:5.1f}%  "
                  f"每步={p['per_step_s']}  已用={p['elapsed_s']}  ETA={p['eta_s']}  "
                  f"区间={p.get('min_step_s')}~{p.get('max_step_s')}")
        if p["status"] in ("done", "error"):
            break
    except Exception as e:
        print("  poll err:", e)
    time.sleep(0.7)

t.join(timeout=60)
print()
print("=== 采样点数量:", len(seen), " ===")
print("=== 进度是否为单调递增 ===")
steps = [s[1] for s in seen]
print("  steps_done 序列:", steps)
print("  单调:", all(b >= a for a, b in zip(steps, steps[1:])))
print("=== 最终响应里的 timing ===")
if RESULT:
    print(json.dumps(RESULT["data"][0].get("timing"), ensure_ascii=False))
PY
