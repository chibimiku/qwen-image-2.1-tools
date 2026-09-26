export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
cd /root/qwen-image-2.1

echo '=== 生成一张验收图（顺便验证进度条在真实前端里跑起来）==='
python - <<'PY'
import base64, json, time, urllib.request
BASE = "http://127.0.0.1:6006"
H = {"Authorization": "Bearer 1730", "Content-Type": "application/json"}
body = json.dumps({"prompt": "a spring lantern festival by the river at night, warm lights, "
                             "reflections on the water, cinematic, detailed",
                   "width": 1024, "height": 1024, "num_inference_steps": 24, "seed": 99}).encode()
t0 = time.time()
req = urllib.request.Request(BASE + "/v1/images/generations", data=body, headers=H)
with urllib.request.urlopen(req, timeout=900) as r:
    res = json.loads(r.read())
item = res["data"][0]
raw = base64.b64decode(item["b64_json"])
out = "/root/qwen-image-2.1/outputs/00_acceptance_lantern.png"
with open(out, "wb") as fh:
    fh.write(raw)
t = item.get("timing", {})
print(f"  {item['width']}x{item['height']} · {time.time()-t0:.1f}s · 每步 {t.get('per_step_s')}s "
      f"· seed={item.get('seed')} · callback_ok={t.get('callback_ok')}")
print("  已存:", out, f"{len(raw)/1024:.0f} KB")
PY

echo
echo '=== inputs 目录 ==='
mkdir -p inputs
ls -la inputs/ 2>/dev/null

echo
echo '=== 最终 outputs 清单 ==='
find outputs -type f -printf '%10s  %TY-%Tm-%Td %TH:%TM  %f\n' | sort -k4
echo "文件数: $(find outputs -type f | wc -l)  总大小: $(du -sh outputs | cut -f1)"

echo
echo '=== 磁盘占用（做镜像前看这个）==='
df -h / /root/autodl-tmp | sed -n '1,4p'
echo
echo '--- 各目录占用 ---'
du -sh /root/qwen-image-2.1 /root/autodl-tmp/Qwen-Image-2.1 /root/miniconda3/lib/python3.12/site-packages 2>/dev/null
echo
echo '--- pip 缓存 / 临时文件（做镜像前建议清）---'
du -sh /root/.cache/pip 2>/dev/null
du -sh /tmp 2>/dev/null
ls -la /root/autodl-tmp/hf /root/autodl-tmp/modelscope 2>/dev/null | head -5
