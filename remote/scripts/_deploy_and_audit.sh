export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
cd /root/qwen-image-2.1

echo '=== 1) 重启服务（新进度代码要重启才生效）==='
bash scripts/serve.sh stop >/dev/null 2>&1
pkill -f 'service/server.py' 2>/dev/null
sleep 3
nohup python service/server.py > logs/service.log 2>&1 &
echo $! > service.pid
echo "pid=$(cat service.pid)"
for i in $(seq 1 60); do
  H=$(curl -s -m 5 localhost:6006/health 2>/dev/null)
  case "$H" in *'"loaded":true'*) echo "READY after $((i*3))s"; break;; esac
  sleep 3
done

echo
echo '=== 2) 文件到位检查 ==='
ls -la service/ui/
echo '--- 关键片段是否在文件里 ---'
for pat in 'callback_on_step_end' '/v1/progress' 'callback_unavailable'; do
  printf '  server.py 含 %-24s : %s\n' "$pat" "$(grep -c "$pat" service/server.py)"
done
for pat in 'progressHTML' 'makePoller' 'p-perstep' 'p-eta'; do
  printf '  index.html 含 %-24s : %s\n' "$pat" "$(grep -c "$pat" service/ui/index.html)"
done

echo
echo '=== 3) 真实进度接口自测（发一个 20 步的请求，同时采样进度）==='
python - <<'PY'
import json, threading, time, urllib.request
BASE = "http://127.0.0.1:6006"
H = {"Authorization": "Bearer 1730", "Content-Type": "application/json"}
def get(p):
    return json.loads(urllib.request.urlopen(
        urllib.request.Request(BASE + p, headers={"Authorization": "Bearer 1730"}), timeout=20).read())

def fire():
    global RES
    body = json.dumps({"prompt": "a spring lantern festival by the river, warm lights",
                       "width": 1024, "height": 1024, "num_inference_steps": 20,
                       "seed": 99, "request_id": "deploy_check_1"}).encode()
    r = urllib.request.Request(BASE + "/v1/images/generations", data=body, headers=H)
    RES = json.loads(urllib.request.urlopen(r, timeout=900).read())
RES = None
threading.Thread(target=fire, daemon=True).start()

seen, t0 = [], time.time()
while time.time() - t0 < 300:
    try:
        p = get("/v1/progress/deploy_check_1")
    except Exception:
        time.sleep(0.5); continue
    cur = (p["steps_done"], p["total"], p["pct"], p["per_step_s"], p["eta_s"], p["status"])
    if not seen or seen[-1] != cur:
        seen.append(cur)
        print(f"  {p['status']:8s} {p['steps_done']:3d}/{p['total']:<3d} {p['pct']:5.1f}%  "
              f"已用 {p['elapsed_s']:5.1f}s  每步 {p['per_step_s']}s  ETA {p['eta_s']}s")
    if p["status"] in ("done", "error"):
        break
    time.sleep(0.6)

steps = [s[0] for s in seen]
print(f"  → 采样 {len(seen)} 次，步数单调递增: {all(b>=a for a,b in zip(steps, steps[1:]))}")
if RES:
    t = RES["data"][0].get("timing", {})
    print(f"  → 响应 timing: 总 {t.get('total_s')}s / {t.get('steps')} 步 / 每步 {t.get('per_step_s')}s / "
          f"prep {t.get('prep_s')}s / callback_ok={t.get('callback_ok')}")
    raw = RES["data"][0]["b64_json"]
    print(f"  → 出图 {RES['size']}，b64 {len(raw)} 字节")
    open("/root/qwen-image-2.1/outputs/deploy_check_lantern.png", "wb").__enter__() if False else None
    import base64
    open("/root/qwen-image-2.1/outputs/deploy_check_lantern.png", "wb").write(base64.b64decode(raw))
    print("  → 已存 outputs/deploy_check_lantern.png")
PY

echo
echo '=== 4) 输出目录盘点 ==='
find /root/qwen-image-2.1/outputs -type f -printf '%10s  %TY-%Tm-%Td %TH:%TM  %p\n' 2>/dev/null | sort -k4
echo "--- 统计 ---"
echo "文件数: $(find /root/qwen-image-2.1/outputs -type f | wc -l)"
echo "总大小: $(du -sh /root/qwen-image-2.1/outputs | cut -f1)"
echo "--- 子目录 ---"
find /root/qwen-image-2.1/outputs -type d
echo
echo '=== 5) 其余可能残留图片的位置 ==='
ls -la /root/qwen-image-2.1/inputs/ 2>/dev/null || echo '  inputs/ 不存在'
ls -la /tmp/*.png 2>/dev/null | head || true
find /root -maxdepth 2 -type f \( -name '*.png' -o -name '*.jpg' \) -newermt '2026-09-26' 2>/dev/null | grep -vE 'autodl-tmp|site-packages' | head -20
