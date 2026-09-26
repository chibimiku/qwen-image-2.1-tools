#!/usr/bin/env bash
# 验证本次改动：multipart 也能带 negative_prompt / guidance_scale；半截尺寸不再 500
set -u
KEY="${KEY:?KEY 未注入}"
API=http://127.0.0.1:6006
OUT=/root/autodl-tmp/fix_check
mkdir -p "$OUT"

# 造一张小参考图
/root/miniconda3/bin/python - <<'PY'
from PIL import Image, ImageDraw
im = Image.new("RGB", (512, 512), (240, 240, 245)); d = ImageDraw.Draw(im)
d.ellipse([140, 140, 372, 372], fill=(210, 60, 60)); im.save("/tmp/fixref.png")
print("ref built")
PY

echo "===== T1: multipart + negative_prompt + guidance_scale ====="
curl -s -m 300 -H "Authorization: Bearer $KEY" \
  -F "image=@/tmp/fixref.png" \
  -F num_inference_steps=6 -F seed=7 -F width=512 -F height=512 -F output_format=png \
  -F guidance_scale=1.0 \
  --form-string "prompt=把背景换成纯白色，主体保持红色圆形不动。" \
  --form-string "negative_prompt=blurry, distorted, extra objects" \
  "$API/v1/images/generations" -o "$OUT/T1.json"
/root/miniconda3/bin/python - <<'PY'
import json, base64
d = json.load(open("/root/autodl-tmp/fix_check/T1.json"))
if "data" in d:
    open("/root/autodl-tmp/fix_check/T1.png","wb").write(base64.b64decode(d["data"][0]["b64_json"]))
    print("  T1 OK", d["data"][0]["width"], "x", d["data"][0]["height"], "elapsed", d["data"][0].get("elapsed_s"))
else:
    print("  T1 ERR", str(d)[:200])
PY

echo "===== T2: 只给 width（半截尺寸，原来会 500） ====="
curl -s -m 300 -w '\nHTTP=%{http_code}\n' -H "Authorization: Bearer $KEY" \
  -F "image=@/tmp/fixref.png" \
  -F num_inference_steps=6 -F seed=7 -F width=512 -F output_format=png \
  --form-string "prompt=保持画面不变，只把红色圆形变成正方形。" \
  "$API/v1/images/generations" -o "$OUT/T2.json"
/root/miniconda3/bin/python - <<'PY'
import json, base64
try:
    d = json.load(open("/root/autodl-tmp/fix_check/T2.json"))
except Exception as e:
    print("  T2 parse err", e); raise SystemExit
if "data" in d:
    open("/root/autodl-tmp/fix_check/T2.png","wb").write(base64.b64decode(d["data"][0]["b64_json"]))
    print("  T2 OK", d["data"][0]["width"], "x", d["data"][0]["height"])
else:
    print("  T2 ERR", str(d)[:200])
PY

echo "===== T3: UI 是否带上新芯片 ====="
curl -s "$API/ui" | grep -c 'renderChips\|insertTag'

echo "===== done ====="
ls -l "$OUT"
