#!/usr/bin/env bash
# 量化"100% 之后还要等多久"：去噪结束后到响应返回，中间花在哪。
set -u
KEY="${KEY:?KEY 未注入}"
API=http://127.0.0.1:6006
PY=/root/miniconda3/bin/python
OUT=/root/autodl-tmp/stall_check
mkdir -p "$OUT"

# 造一张接近用户那次的竖长图（512x1216）
$PY - <<'PY'
from PIL import Image, ImageDraw
im = Image.new("RGB", (512, 1216), (240, 242, 248))
d = ImageDraw.Draw(im)
d.ellipse([120, 300, 392, 572], fill=(200, 70, 90))
d.rectangle([100, 700, 412, 1000], fill=(60, 90, 200))
im.save("/tmp/stall_ref.png")
print("ref built 512x1216")
PY

echo "===== 编辑：显式 width=height=1024（复刻用户配置） ====="
$PY - "$API" "$KEY" "$OUT" <<'PY'
import json, time, sys, urllib.request, uuid, mimetypes, os, base64
api, key, out = sys.argv[1], sys.argv[2], sys.argv[3]

def multipart(fields, files):
    b = uuid.uuid4().hex
    body = b""
    for k, v in fields.items():
        body += (f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n').encode()
    for k, path in files:
        name = os.path.basename(path)
        ct = mimetypes.guess_type(name)[0] or "application/octet-stream"
        body += (f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\n'
                 f'Content-Type: {ct}\r\n\r\n').encode()
        body += open(path, "rb").read() + b"\r\n"
    body += f"--{b}--\r\n".encode()
    return body, f"multipart/form-data; boundary={b}"

rid = "req_stall" + uuid.uuid4().hex[:6]
body, ct = multipart(
    {"prompt": "把画面变成干净的白色背景，保留主体",
     "num_inference_steps": "30", "width": "1024", "height": "1024",
     "output_format": "png", "request_id": rid},
    [("image", "/tmp/stall_ref.png")])

req = urllib.request.Request(api + "/v1/images/generations", data=body,
                            headers={"Content-Type": ct, "Authorization": "Bearer " + key})
t0 = time.time()
resp = urllib.request.urlopen(req, timeout=900)
t_header = time.time() - t0
raw = resp.read()
t_done = time.time() - t0
print(f"  响应头到达: {t_header:.2f}s")
print(f"  响应体读完: {t_done:.2f}s   （体 {len(raw)/1e6:.2f} MB）")
print(f"  → 去噪结束到收完数据的差值 ≈ {t_done - t_header:.2f}s（这就是进度条 100% 后的空白）")
d = json.loads(raw)
it = d["data"][0]
print(f"  输出: {it['width']}x{it['height']}  elapsed_s={it['elapsed_s']}")
tm = it.get("timing", {})
print(f"  timing: {json.dumps(tm, ensure_ascii=False)}")
open(out + "/edit_1024.png", "wb").write(base64.b64decode(it["b64_json"]))
PY

echo
echo "===== 对比：不填宽高（跟随参考图） ====="
$PY - "$API" "$KEY" "$OUT" <<'PY'
import json, time, sys, urllib.request, uuid, mimetypes, os, base64
api, key, out = sys.argv[1], sys.argv[2], sys.argv[3]

def multipart(fields, files):
    b = uuid.uuid4().hex
    body = b""
    for k, v in fields.items():
        body += (f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n').encode()
    for k, path in files:
        name = os.path.basename(path)
        ct = mimetypes.guess_type(name)[0] or "application/octet-stream"
        body += (f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\n'
                 f'Content-Type: {ct}\r\n\r\n').encode()
        body += open(path, "rb").read() + b"\r\n"
    body += f"--{b}--\r\n".encode()
    return body, f"multipart/form-data; boundary={b}"

rid = "req_free" + uuid.uuid4().hex[:6]
body, ct = multipart(
    {"prompt": "把画面变成干净的白色背景，保留主体",
     "num_inference_steps": "30", "output_format": "png", "request_id": rid},
    [("image", "/tmp/stall_ref.png")])

req = urllib.request.Request(api + "/v1/images/generations", data=body,
                            headers={"Content-Type": ct, "Authorization": "Bearer " + key})
t0 = time.time()
resp = urllib.request.urlopen(req, timeout=900)
raw = resp.read()
print(f"  总耗时: {time.time()-t0:.2f}s")
d = json.loads(raw)
it = d["data"][0]
print(f"  输出: {it['width']}x{it['height']}  elapsed_s={it['elapsed_s']}")
open(out + "/edit_follow.png", "wb").write(base64.b64decode(it["b64_json"]))
PY

echo "===== done ====="
ls -l "$OUT"
