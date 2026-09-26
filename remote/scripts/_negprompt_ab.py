#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""多 seed 对照：负面提示词 + CFG 到底有没有用。

上一次对照每个变体只跑 1 个 seed，结论不可靠（生成是概率性的）。
这次对 6 个 seed 各跑「基准」与「负面词+CFG」两遍，用 anatomy_check 统计失败次数。

跑两轮：文生图（纯文本，无参考图）与编辑（带参考图），因为官方说 2.1 是按无引导设计的，
两者可能表现不同。
"""
import base64
import io
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, "/root/qwen-image-2.1")
sys.path.insert(0, "/root/qwen-image-2.1/service")
from PIL import Image, ImageDraw                                # noqa: E402

KEY = os.environ.get("KEY", "")
API = "http://127.0.0.1:6006"
SEEDS = [11, 22, 33, 44, 55, 66]
STEPS = 14
NEG = ("extra limbs, extra legs, extra arms, fused limbs, merged legs, "
       "malformed hands, missing limbs, conjoined figures, distorted anatomy")

# 姿态故意复杂（两人类交缠），这是多腿最容易出现的场景
P_EDIT = ("Change only the pose in <image1>. The female character is being carried "
          "piggyback by an adult man, her legs around his sides. Keep her face, hairstyle "
          "and anime art style as in <image1>. Full body, both figures inside the frame, "
          "wide angle, no cropping.")
P_T2I = ("anime style, two people, a woman carried piggyback by a man, dynamic pose, "
         "full body, plain background, clean lines")


def make_ref(path):
    im = Image.new("RGB", (1280, 1696), (246, 244, 240))
    d = ImageDraw.Draw(im)
    for cx in (320, 960):
        d.ellipse([cx - 120, 240, cx + 120, 480], fill=(247, 226, 212))
        d.polygon([(cx, 240), (cx - 115, 175), (cx + 115, 175)], fill=(238, 226, 170))
        d.rectangle([cx - 115, 500, cx + 115, 850], fill=(70, 80, 110))
        d.rectangle([cx - 105, 850, cx - 30, 1180], fill=(70, 80, 110))
        d.rectangle([cx + 30, 850, cx + 105, 1180], fill=(70, 80, 110))
        d.ellipse([cx - 125, 1180, cx - 10, 1240], fill=(50, 55, 70))
        d.ellipse([cx + 10, 1180, cx + 125, 1240], fill=(50, 55, 70))
        d.line([(cx - 115, 550), (cx - 190, 800)], fill=(70, 80, 110), width=32)
        d.line([(cx + 115, 550), (cx + 190, 800)], fill=(70, 80, 110), width=32)
    im.save(path)
    return path


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


def gen(prompt, seed, cfg=None, ref=None, w=1024, h=1024):
    fields = {"prompt": prompt, "num_inference_steps": str(STEPS), "seed": str(seed),
              "output_format": "png", "width": str(w), "height": str(h)}
    if cfg:
        fields["negative_prompt"] = NEG
        fields["true_cfg_scale"] = str(cfg)
    files = [("image", ref)] if ref else []
    if ref:
        body, ct = multipart(fields, files)
        req = urllib.request.Request(API + "/v1/images/generations", data=body,
                                     headers={"Content-Type": ct,
                                              "Authorization": "Bearer " + KEY})
    else:
        req = urllib.request.Request(API + "/v1/images/generations",
                                     data=json.dumps(fields).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": "Bearer " + KEY})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=900).read())
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read()[:120].decode('utf-8', 'replace')}"
    return base64.b64decode(d["data"][0]["b64_json"]), ""


def inspect(png):
    try:
        from anatomy_check import inspect_image
        return inspect_image(Image.open(io.BytesIO(png)).convert("RGB"), "")
    except Exception as e:                                             # noqa: BLE001
        return {"passed": None, "reason": str(e)[:50]}


ref = make_ref("/tmp/neg_ref.png")
out = "/tmp/neg_out"
os.makedirs(out, exist_ok=True)

print(f"负面词：{NEG}")
print(f"每格 {len(SEEDS)} 个 seed，步数 {STEPS}\n")

summary = {}
for mode, prompt, use_ref in (("编辑(带参考图)", P_EDIT, ref), ("文生图", P_T2I, None)):
    print("=" * 78)
    print(f"■ {mode}")
    print("=" * 78)
    for label, cfg in (("基准 CFG=1 无负面词", None), ("负面词 + CFG=2.5", 2.5)):
        fails, vers = 0, []
        for s in SEEDS:
            png, err = gen(prompt, s, cfg, use_ref)
            if png is None:
                print(f"  {label:20} seed={s:3}  请求失败：{err}")
                continue
            v = inspect(png)
            if not v.get("passed"):
                fails += 1
            vers.append((s, "FAIL" if not v.get("passed") else "pass",
                         (v.get("reason") or "")[:44]))
            open(f"{out}/{mode[:2]}_{label[:2]}_{s}.png", "wb").write(png)
        print(f"  {label:20} 审图 FAIL {fails}/{len(SEEDS)}")
        for s, r, why in vers:
            print(f"      seed={s:3}  {r:4}  {why}")
        summary[f"{mode}|{label}"] = f"{fails}/{len(SEEDS)}"
    print()

print("=" * 78)
print("汇总（anatomy_check 判 FAIL 的次数，越少越好）")
for k, v in summary.items():
    print(f"  {k:38} {v}")
print(f"\n图在 {out}/")
