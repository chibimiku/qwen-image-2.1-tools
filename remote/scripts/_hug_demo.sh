export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
B=localhost:6006
H="Authorization: Bearer $QWEN_API_KEY"

python3 - <<'PY'
from PIL import Image, ImageDraw
# 两张更像"人"的参考图
def person(path, size, hair, cloth):
    w, h = size
    im = Image.new("RGB", size, (245, 240, 232))
    d = ImageDraw.Draw(im)
    d.ellipse([w*0.30, h*0.06, w*0.70, h*0.30], fill=hair)             # 头发
    d.ellipse([w*0.33, h*0.10, w*0.67, h*0.32], fill=(245, 215, 190))  # 脸
    d.polygon([(w*0.5, h*0.30), (w*0.78, h*0.62), (w*0.22, h*0.62)], fill=cloth)  # 上身
    d.rectangle([w*0.28, h*0.60, w*0.72, h*0.98], fill=cloth)
    im.save(path)
person("/tmp/hug_a.png", (768, 1024), (60, 40, 30), (90, 130, 200))
person("/tmp/hug_b.png", (768, 1024), (190, 120, 80), (200, 90, 110))
print("参考图已生成: /tmp/hug_a.png /tmp/hug_b.png")
PY

echo
echo '=== 目标场景：两个人拥抱（两张参考图，竖构图 1184×1600）==='
python3 - <<'PY'
import base64, json, os, time, urllib.request
B = "http://127.0.0.1:6006"
K = os.environ["QWEN_API_KEY"]

import uuid
boundary = "----qwen" + uuid.uuid4().hex
parts = []
def field(name, value):
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
def filefield(name, path):
    fn = os.path.basename(path)
    with open(path, "rb") as fh:
        data = fh.read()
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{fn}"\r\n'
                 f'Content-Type: image/png\r\n\r\n'.encode() + data + b"\r\n")

field("prompt", "These two people are hugging each other warmly, waist up, "
                "standing on a seaside veranda at golden hour, soft light, detailed faces")
field("num_inference_steps", "14")
field("seed", "20260926")
field("width", "1184")
field("height", "1600")
filefield("image", "/tmp/hug_a.png")
filefield("image", "/tmp/hug_b.png")
parts.append(f'--{boundary}--\r\n'.encode())
body = b"".join(parts)

req = urllib.request.Request(B + "/v1/images/edits", data=body, method="POST",
    headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
             "Authorization": "Bearer " + K})
t0 = time.time()
with urllib.request.urlopen(req, timeout=900) as r:
    d = json.loads(r.read())
it = d["data"][0]
raw = base64.b64decode(it["b64_json"])
out = "/root/qwen-image-2.1/outputs/hug_two_people.png"
open(out, "wb").write(raw)
print(f"  输出 {d['size']} · {time.time()-t0:.1f}s · 每步 {it['timing']['per_step_s']}s")
print(f"  已存 {out} ({len(raw)/1024:.0f} KB)")
PY

echo
echo '=== 输出目录 ==='
ls -la /root/qwen-image-2.1/outputs/ | tail -4
