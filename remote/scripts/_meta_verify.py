#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 PNG 元数据：写入 → 读回 → 兼容性 → 参考图 hash → 可复现所需字段齐全。"""
import base64
import hashlib
import io
import json
import os
import sys
import urllib.request

sys.path.insert(0, "/root/qwen-image-2.1/tools")

from PIL import Image, ImageDraw, PngImagePlugin   # noqa: E402

KEY = os.environ.get("KEY", "")
API = "http://127.0.0.1:6006"
CHUNK = "qwen_image_21"


def post_json(body):
    req = urllib.request.Request(API + "/v1/images/generations",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    if KEY:
        req.add_header("Authorization", "Bearer " + KEY)
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())


def make_ref(path):
    im = Image.new("RGB", (512, 640), (235, 238, 245))
    d = ImageDraw.Draw(im)
    d.ellipse([120, 160, 392, 432], fill=(200, 80, 100))
    im.save(path)
    return path


def read_chunk(png_bytes):
    im = Image.open(io.BytesIO(png_bytes))
    im.load()
    raw = im.info.get(CHUNK)
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    return json.loads(raw)


ok = True


def check(label, cond, extra=""):
    global ok
    ok = ok and bool(cond)
    print(f"  [{'OK' if cond else 'FAIL'}] {label}{(' — ' + str(extra)) if extra else ''}")


print("=== 1. 文生图（留空 seed）：元数据是否写全 ===")
resp = post_json({"prompt": "一个红色立方体放在白色桌面上，影棚光", "num_inference_steps": 8,
                  "width": 512, "height": 512, "output_format": "png"})
item = resp["data"][0]
png = base64.b64decode(item["b64_json"])
meta = read_chunk(png)
check("PNG 里有 qwen_image_21 元数据", meta is not None)
if meta:
    r, m, o = meta.get("request", {}), meta.get("model", {}), meta.get("output", {})
    check("schema 版本化", meta.get("schema") and isinstance(meta.get("schema_version"), int),
          f"{meta.get('schema')} v{meta.get('schema_version')}")
    check("prompt 原文", r.get("prompt") == "一个红色立方体放在白色桌面上，影棚光", r.get("prompt"))
    check("seed 记录且与响应一致", r.get("seed") == item.get("seed"), r.get("seed"))
    check("seed_given=false（自动掷）", r.get("seed_given") is False)
    check("尺寸/steps", (r.get("width"), r.get("height"), r.get("num_inference_steps")) == (512, 512, 8))
    check("模型 hash（全量 sha256）", len(m.get("weights_sha256") or "") == 64, (m.get("weights_sha256") or "")[:16])
    check("模型 hash 状态 ok", m.get("state") == "ok")
    check("生成器版本", bool((meta.get("generator") or {}).get("version")))
    check("环境信息", bool((meta.get("environment") or {}).get("torch")))
    check("耗时信息", bool((meta.get("timing") or {}).get("total_s")))
    check("输出 content_sha256（像素内容哈希，写文件里的那个）",
          len(o.get("content_sha256") or "") == 64)
    # 文件自身的完整哈希不能存在文件里（自指），所以 PNG 内的 png_sha256 必须是空的；
    # 它只出现在 API 响应/列表里，用来核对"手里的文件是不是服务端发出的那个"。
    check("PNG 内 png_sha256 为空（自指哈希进不了文件，这是设计）",
          o.get("png_sha256") in (None, ""), repr(o.get("png_sha256")))
    actual = hashlib.sha256(png).hexdigest()
    check("响应里的 png_sha256 与收到的文件一致",
          (item.get("metadata") or {}).get("png_sha256") == actual,
          f"{actual[:16]} vs {((item.get('metadata') or {}).get('png_sha256') or 'None')[:16]}")
    # content_sha256 按像素算（不按 PNG 字节 —— 编码依赖 Pillow/zlib 版本），可本地复算
    with Image.open(io.BytesIO(png)) as _im:
        _im.load()
        _im2 = _im if _im.mode == "RGBA" else _im.convert("RGBA")
        _h = hashlib.sha256()
        _h.update(f"RGBA\0{_im2.width}\0{_im2.height}\0".encode())
        _h.update(_im2.tobytes())
        expect_content = _h.hexdigest()
    check("content_sha256 可由像素复算出来（与 PNG 编码版本无关）",
          expect_content == o.get("content_sha256"))

print("\n=== 2. 响应里的精简 metadata（不解 PNG 也能拿） ===")
md = item.get("metadata") or {}
check("有 metadata 字段", bool(md))
check("含 model_hash", bool(md.get("model_hash")), md.get("model_hash"))
check("含 png_sha256", bool(md.get("png_sha256")))
check("响应里没有塞完整 meta（省体积）", "meta" not in item)

print("\n=== 3. 参考图的 hash 是否进元数据（多图 + <imageN> 对应） ===")
a = make_ref("/tmp/meta_ref_a.png")
b = make_ref("/tmp/meta_ref_b.png")
import mimetypes                                                     # noqa: E402
import uuid                                                          # noqa: E402


def multipart(fields, files):
    bd = uuid.uuid4().hex
    body = b""
    for k, v in fields.items():
        body += (f'--{bd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n').encode()
    for k, path in files:
        name = os.path.basename(path)
        ct = mimetypes.guess_type(name)[0] or "application/octet-stream"
        body += (f'--{bd}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\n'
                 f'Content-Type: {ct}\r\n\r\n').encode()
        body += open(path, "rb").read() + b"\r\n"
    body += f"--{bd}--\r\n".encode()
    return body, f"multipart/form-data; boundary={bd}"


body, ct = multipart({"prompt": "把<image1>和<image2>放在同一张白底图里",
                      "num_inference_steps": "6", "width": "512", "height": "512",
                      "output_format": "png"}, [("image", a), ("image", b)])
req = urllib.request.Request(API + "/v1/images/generations", data=body,
                             headers={"Content-Type": ct})
if KEY:
    req.add_header("Authorization", "Bearer " + KEY)
with urllib.request.urlopen(req, timeout=600) as r:
    resp2 = json.loads(r.read())
png2 = base64.b64decode(resp2["data"][0]["b64_json"])
meta2 = read_chunk(png2)
ins = (meta2 or {}).get("inputs") or []
check("记录了两张输入图", len(ins) == 2, len(ins))
check("编号对应 <image1>/<image2>", [x.get("index") for x in ins] == [1, 2])
check("每张都有 sha256", all(len(x.get("sha256") or "") == 64 for x in ins))
check("记了原始文件名", [x.get("name") for x in ins] == ["meta_ref_a.png", "meta_ref_b.png"],
      [x.get("name") for x in ins])
# 像素级 hash：同一张图换个容器应得到同一个 sha256
im_a = Image.open(a).convert("RGBA")
buf = io.BytesIO()
im_a.save(buf, format="PNG", compress_level=1)
expect_a = hashlib.sha256(buf.getvalue()).hexdigest()
check("输入图 hash 按像素算（与同参数 PNG 编码一致）", ins[0]["sha256"] == expect_a)

print("\n=== 4. 前向兼容：给元数据塞一个未知字段，读取方应忽略而不是报错 ===")
im = Image.open(io.BytesIO(png))
im.load()
fake = dict(meta)
fake["future_field_v2"] = {"totally": "unknown", "nested": [1, 2, 3]}
info = PngImagePlugin.PngInfo()
info.add_itxt(CHUNK, json.dumps(fake, ensure_ascii=False), zip=False)
buf = io.BytesIO()
im.save(buf, format="PNG", compress_level=1, pnginfo=info)
back = read_chunk(buf.getvalue())
check("未知字段被原样保留（不丢数据）", back.get("future_field_v2") == fake["future_field_v2"])
check("老字段仍然可读", (back.get("request") or {}).get("prompt") == meta["request"]["prompt"])
known = {"schema", "schema_version", "generator", "model", "request", "inputs",
         "output", "timing", "environment", "anatomy_check"}
check("读取方能识别出这是新字段", bool(set(back) - known), sorted(set(back) - known))

print("\n=== 5. 体积开销 ===")
bare = io.BytesIO()
Image.open(io.BytesIO(png)).load()
Image.open(io.BytesIO(png)).save(bare, format="PNG", compress_level=1)
print(f"  512x512：无元数据 {len(bare.getvalue()) / 1024:.1f} KB → "
      f"带元数据 {len(png) / 1024:.1f} KB（+{(len(png) - len(bare.getvalue())) / 1024:.1f} KB）")
check("开销可接受（<32KB）", len(png) - len(bare.getvalue()) < 32768,
      f"+{len(png) - len(bare.getvalue())} B")

print("\n结论:", "全部通过 ✅" if ok else "有失败项 ❌")
sys.exit(0 if ok else 1)
