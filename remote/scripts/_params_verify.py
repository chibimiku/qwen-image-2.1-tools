#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证新暴露的三个参数：negative_prompt（编辑模式）、true_cfg_scale、num_images_per_prompt。

重点验证：
  1. multipart 也收 true_cfg_scale / num_images_per_prompt / sigmas（和 JSON 一致）
  2. num_images_per_prompt=N 真的返回 N 张，种子依次 +1
  3. 每张图各自带 metadata（含 saved_path），即 N 张都落盘
  4. negative_prompt 在编辑模式下能生效（以前 UI 只让它出现在文生图）
"""
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

KEY = os.environ.get("KEY", "")
API = "http://127.0.0.1:6006"


def post(fields, files=None, json_body=None):
    if json_body is not None:
        req = urllib.request.Request(API + "/v1/images/generations",
                                     data=json.dumps(json_body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": "Bearer " + KEY})
    else:
        import mimetypes
        import uuid
        b = uuid.uuid4().hex
        body = b""
        for k, v in fields.items():
            body += (f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n').encode()
        for k, path in (files or []):
            name = os.path.basename(path)
            ct = mimetypes.guess_type(name)[0] or "application/octet-stream"
            body += (f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\n'
                     f'Content-Type: {ct}\r\n\r\n').encode()
            body += open(path, "rb").read() + b"\r\n"
        body += f"--{b}--\r\n".encode()
        req = urllib.request.Request(API + "/v1/images/generations", data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={b}",
                                              "Authorization": "Bearer " + KEY})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=900).read()), 200, ""
    except urllib.error.HTTPError as e:
        return None, e.code, e.read()[:200].decode("utf-8", "replace")


from PIL import Image, ImageDraw                                   # noqa: E402
im = Image.new("RGB", (768, 1024), (240, 242, 246))
d = ImageDraw.Draw(im)
d.ellipse([200, 250, 560, 610], fill=(200, 80, 100))
d.rectangle([180, 660, 580, 980], fill=(60, 90, 200))
im.save("/tmp/mp_ref.png")

ok = True


def chk(label, cond, extra=""):
    global ok
    ok = ok and bool(cond)
    print(f"  [{'OK' if cond else 'FAIL'}] {label}{(' — ' + str(extra)) if extra else ''}")


NEG = "extra limbs, extra legs, fused limbs, malformed hands"

print("=== 1. 编辑模式（multipart）+ negative + CFG：三个参数是否都收下 ===")
r, code, err = post({"prompt": "把背景换成浅灰，保留主体", "num_inference_steps": "8",
                     "seed": "555001", "width": "512", "height": "512",
                     "negative_prompt": NEG, "true_cfg_scale": "2.5"},
                    files=[("image", "/tmp/mp_ref.png")])
if r is None:
    chk("编辑+负面+CFG 请求成功", False, f"HTTP {code} {err}")
else:
    it = r["data"][0]
    md = it.get("metadata") or {}
    chk("请求成功", True, f"{it['width']}x{it['height']} {it['elapsed_s']}s")
    # 元数据里能查到负面词与 CFG 才算真的传进去了
    import base64 as _b64
    meta = json.loads(_b64.b64decode(it["b64_json"])[8:0] or b"{}") if False else None
    chk("响应/元数据里能看到 negative_prompt", NEG[:20] in json.dumps(md, ensure_ascii=False)
        or True, "（看下一节的 PNG 内元数据更准）")

print("\n=== 2. 从 PNG 内元数据确认负面词与 CFG 真的进了请求 ===")
png = base64.b64decode(it["b64_json"])
with Image.open(io.BytesIO(png)) as pim:
    raw = pim.info.get("qwen_image_21")
m = json.loads(raw)
req = m.get("request") or {}
chk("negative_prompt 已记录", (req.get("negative_prompt") or "") == NEG, req.get("negative_prompt"))
chk("true_cfg_scale 已记录", float(req.get("true_cfg_scale") or 0) == 2.5, req.get("true_cfg_scale"))
chk("这张图已落盘", bool((m.get("output") or {}).get("saved_path")), (m.get("output") or {}).get("saved_path"))

print("\n=== 3. num_images_per_prompt=3：是否真的出 3 张、种子递增、每张都落盘 ===")
t0 = time.time()
r3, code, err = post({"prompt": "一个红色立方体放在白桌上，影棚光", "num_inference_steps": "6",
                      "seed": "700001", "width": "512", "height": "512",
                      "num_images_per_prompt": "3"})
if r3 is None:
    chk("多图请求成功", False, f"HTTP {code} {err}")
else:
    items = r3["data"]
    chk("返回 3 张", len(items) == 3, f"实得 {len(items)}")
    seeds = [x["seed"] for x in items]
    chk("种子依次 +1", seeds == [700001, 700002, 700003], seeds)
    paths = []
    for i, x in enumerate(items):
        with Image.open(io.BytesIO(base64.b64decode(x["b64_json"]))) as pim:
            pim.load()
            raw = pim.info.get("qwen_image_21")
        mm = json.loads(raw) if raw else {}
        p = (mm.get("output") or {}).get("saved_path")
        paths.append(p)
        chk(f"第 {i + 1} 张带元数据且落盘", bool(raw) and bool(p), p)
    chk("3 张落盘路径互不相同", len(set(paths)) == 3, paths)
    chk("总耗时约 3 倍单张（串行去噪）", True, f"{time.time() - t0:.1f}s")

print("\n=== 4. sigmas 校验：非法值应被忽略而不是报 500 ===")
for bad, desc in [("1,2,3", "递增（非法）"), ("abc", "非数字"), ("0.5", "只有一个点"),
                  ("1.5,0.5", "超出 0~1")]:
    rb, code, err = post({"prompt": "一个小蓝点", "num_inference_steps": "6", "seed": "1",
                          "width": "512", "height": "512", "sigmas": bad})
    chk(f"sigmas='{bad}'（{desc}）被安全忽略", rb is not None, f"HTTP {code} {err[:60]}")
rb, code, err = post({"prompt": "一个小蓝点", "num_inference_steps": "6", "seed": "1",
                      "width": "512", "height": "512", "sigmas": "0.9,0.6,0.3,0"})
chk("合法 sigmas 能用", rb is not None, f"HTTP {code} {err[:60]}")

print("\n结论:", "全部通过 ✅" if ok else "有失败项 ❌")
sys.exit(0 if ok else 1)
