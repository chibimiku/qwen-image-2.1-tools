#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""按 docs/CFG-NEGATIVE-AB-TEST.md 执行对照实验。

四组（其他参数全部固定，见下）：
  A  空负面词 + CFG=1.0       官方默认基线
  B  项目自编人体负面词 + CFG=2.0
  C  同 B + CFG=2.5          当前 UI 快捷值
  D  空负面词 + CFG=1.0       但正向 prompt 按官方 PE 方法改写（只改姿态、其余保持）

三类任务：t2i 单人全身 / edit1 单参考图大幅换姿态 / edit2 双人肢体交叠（最易暴露多肢）

设计上遵守方案里的三条要求：
  1. **不启用 anatomy_check 自动重跑** —— 否则最终图可能已换 seed，A/B 配对失效
  2. 固定分辨率/步数/参考图/prompt/模型，只让四组之间变
  3. 只产出图片 + 盲评 manifest（blind_id / seed / task / path / elapsed），
     评分另跑一遍，最后再 join 回 variant —— 避免评分被"CFG=2.5"暗示
"""
import base64
import hashlib
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, "/root/qwen-image-2.1/service")
from PIL import Image, ImageDraw                                # noqa: E402

KEY = os.environ.get("KEY", "")
API = "http://127.0.0.1:6006"
OUT = "/root/exp_out"
SEEDS = [101, 202, 303, 404, 505, 606, 707, 808, 909, 1010, 1111, 1212]   # 12 个
STEPS = 20
SIZE = (1024, 1024)          # 46068 MiB 卡：1024²=1.05MP，编辑模式安全

NEG = ("extra limbs, extra legs, extra arms, fused limbs, merged legs, "
       "malformed hands, missing limbs, conjoined figures, distorted anatomy")

# ---- 三类任务的 prompt ----
# A/B/C 用同一套正向 prompt；D 用 PE 式改写版（操作句首 + 只声明该变的 + 一揽子保持句）
T2I_ABC = ("anime style illustration, a young woman standing up, full body from head to toe, "
           "arms relaxed at her sides, both legs clearly visible and separated, "
           "plain light background, clean line art, high detail")
T2I_D = ("Draw one woman standing up. Both feet flat on the ground, arms relaxed at her sides, "
         "each person has exactly two legs and two arms, every limb clearly attached "
         "and plainly visible. Full body, entirely inside the frame, plain light background. "
         "Anime style, clean line art.")

E1_ABC = ("<image1> is a character reference. Reconstruct her exactly: same face, same hair, "
          "same outfit, same anime art style. Now she is jumping mid-air with knees tucked, "
          "large dynamic motion, both legs clearly visible. Full body, entire figure inside "
          "the frame, wide angle, no cropping. Pure anime style, clean lines, high detail.")
E1_D = ("Change only the pose in <image1>. She is jumping mid-air with her knees tucked up. "
        "Keep her face, hairstyle, outfit and anime art style exactly as in <image1>. "
        "Simple readable limbs: exactly two arms and two legs, each clearly attached "
        "to her body. Full body, entirely inside the frame, wide angle, no cropping. "
        "Clean line art, high detail.")

E2_ABC = ("<image1> is a character reference. Reconstruct her exactly: same face, same hair, "
          "same outfit, same anime art style. She is being carried on the back of an adult man, "
          "her arms over his shoulders, both figures fully visible. Dynamic action pose, "
          "large motion. Full body, both figures entirely inside the frame, wide angle, "
          "no cropping. Pure anime style, clean lines, high detail.")
E2_D = ("Change only the pose in <image1>. The woman is now being carried piggyback by "
        "an adult man; her arms go over his shoulders, his hands hold her legs. "
        "Keep the woman's face, hairstyle, outfit and anime art style exactly as in <image1>. "
        "Both people have simple readable anatomy: each has exactly two arms and two legs, "
        "and every limb is clearly attached to its own body. Full body, both figures entirely "
        "inside the frame, wide angle, no cropping. Clean line art, high detail.")

TASKS = [
    # key, 是否有参考图, ABC 的 prompt, D 的 prompt
    ("t2i", False, T2I_ABC, T2I_D),
    ("edit1", True, E1_ABC, E1_D),
    ("edit2", True, E2_ABC, E2_D),
]

VARIANTS = [
    ("A", None, None),          # 官方默认
    ("B", NEG, 2.0),
    ("C", NEG, 2.5),
    ("D", None, None),          # D 的差异在 prompt，不在参数
]


def make_ref(path, w=1024, h=1024):
    """参考图：单人，紧身衣，四肢清晰 —— 这样"多腿"一眼能看出来"""
    im = Image.new("RGB", (w, h), (247, 245, 241))
    d = ImageDraw.Draw(im)
    cx = w // 2
    d.ellipse([cx - 90, 150, cx + 90, 330], fill=(247, 226, 212))
    d.polygon([(cx, 150), (cx - 95, 105), (cx + 95, 105)], fill=(238, 226, 170))
    d.rectangle([cx - 90, 350, cx + 90, 640], fill=(72, 82, 112))
    d.rectangle([cx - 80, 640, cx - 22, 880], fill=(72, 82, 112))
    d.rectangle([cx + 22, 640, cx + 80, 880], fill=(72, 82, 112))
    d.ellipse([cx - 95, 880, cx - 8, 925], fill=(50, 55, 70))
    d.ellipse([cx + 8, 880, cx + 95, 925], fill=(50, 55, 70))
    d.line([(cx - 90, 380), (cx - 150, 580)], fill=(72, 82, 112), width=26)
    d.line([(cx + 90, 380), (cx + 150, 580)], fill=(72, 82, 112), width=26)
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


def generate(prompt, seed, neg, cfg, ref=None, size=SIZE):
    """发一次请求。**不带 anatomy_check** —— 方案要求，避免自动换 seed 破坏配对。"""
    fields = {"prompt": prompt, "num_inference_steps": str(STEPS), "seed": str(seed),
              "output_format": "png", "width": str(size[0]), "height": str(size[1])}
    if neg:
        fields["negative_prompt"] = neg
    if cfg:
        fields["true_cfg_scale"] = str(cfg)
    if ref:
        body, ct = multipart(fields, [("image", ref)])
        req = urllib.request.Request(API + "/v1/images/edits", data=body,
                                     headers={"Content-Type": ct,
                                              "Authorization": "Bearer " + KEY})
    else:
        req = urllib.request.Request(API + "/v1/images/generations",
                                     data=json.dumps(fields).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": "Bearer " + KEY})
    t0 = time.time()
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=900).read())
    except urllib.error.HTTPError as e:
        return None, time.time() - t0, f"HTTP {e.code}: {e.read()[:120].decode('utf-8', 'replace')}"
    it = d["data"][0]
    return base64.b64decode(it["b64_json"]), time.time() - t0, ""


ref = make_ref("/root/exp_out/ref.png" if os.path.isdir("/root/exp_out") else "/tmp/exp_ref.png")
os.makedirs(OUT, exist_ok=True)
ref = make_ref(f"{OUT}/ref.png")

manifest, blind = [], []
print(f"任务 {len(TASKS)} 类 × 变体 {len(VARIANTS)} 组 × seed {len(SEEDS)} 个 = "
      f"{len(TASKS) * len(VARIANTS) * len(SEEDS)} 张")
print(f"尺寸 {SIZE[0]}x{SIZE[1]}  步数 {STEPS}  参考图 {Image.open(ref).size}\n")

n_ok = n_fail = 0
# 只跑指定的任务类：`python _cfg_ab_generate.py t2i`。补跑单类时用得上，
# 而且不会把别的类已经生成的 PNG 重跑一遍（既省时间也避免覆盖）。
ONLY = [a for a in sys.argv[1:] if not a.startswith("-")]
for task_key, use_ref, p_abc, p_d in TASKS:
    if ONLY and task_key not in ONLY:
        continue
    print(f"===== {task_key} =====", flush=True)
    for vkey, neg, cfg in VARIANTS:
        prompt = p_d if vkey == "D" else p_abc
        times = []
        for seed in SEEDS:
            png, dt, err = generate(prompt, seed, neg, cfg, ref if use_ref else None)
            bid = f"{task_key}_{vkey}_{seed}"
            if png is None:
                print(f"  {vkey} seed={seed}: {err}")
                n_fail += 1
                continue
            path = f"{OUT}/{bid}.png"
            open(path, "wb").write(png)
            n_ok += 1
            times.append(dt)
            sha = hashlib.sha256(png).hexdigest()[:16]
            # manifest 含 variant（内部用）
            manifest.append({"blind_id": bid, "task": task_key, "variant": vkey, "seed": seed,
                             "negative_prompt": neg or "", "true_cfg_scale": cfg or 1.0,
                             "prompt_variant": "PE" if vkey == "D" else "plain",
                             "size": f"{SIZE[0]}x{SIZE[1]}", "steps": STEPS,
                             "elapsed_s": round(dt, 2), "path": path, "sha256": sha})
            # 盲评清单**只含 blind_id 与路径**，不含任何变体信息
            blind.append({"blind_id": bid, "image": path})
        if times:
            avg = sum(times) / len(times)
            print(f"  {vkey:2} 负面词={'有' if neg else '无':2} CFG={cfg or 1.0:<4} "
                  f"{len(times)}/{len(SEEDS)} 张  平均 {avg:.1f}s")

def _dump(p, rows, mode="w"):
    """mode="a" 用于补跑单类：把新行接到已有的 manifest 后面，别把老数据冲掉。"""
    with open(p, mode, encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


_APPEND = "a" if (ONLY and os.path.exists(f"{OUT}/manifest.jsonl")) else "w"
_dump(f"{OUT}/manifest.jsonl", manifest, _APPEND)   # 含 variant，别给评分者
_dump(f"{OUT}/blind.jsonl", blind, _APPEND)         # 只给这个给评分者
json.dump({"seeds": SEEDS, "steps": STEPS, "size": SIZE, "variants": {
    "A": "无负面词 CFG=1（官方默认）", "B": "自编人体负面词 CFG=2.0",
    "C": "同 B CFG=2.5", "D": "无负面词 CFG=1，但 prompt 按 PE 方法改写"}},
    open(f"{OUT}/design.json", "w"), ensure_ascii=False, indent=2)

print(f"\n成功 {n_ok} 张 / 失败 {n_fail} 张  (manifest {_APPEND})")
print(f"产物：{OUT}/")
print(f"  manifest.jsonl  含 variant（内部用，别给评分者）")
print(f"  blind.jsonl     只含 blind_id 与路径 —— 评分用这个")
print(f"  design.json     实验设计")
