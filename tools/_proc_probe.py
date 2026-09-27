# -*- coding: utf-8 -*-
"""量 processor 单独加载与调用的耗时，决定 tokenize 接口能不能按需加载。

  python tools/_proc_probe.py

关注三点：
  1. AutoProcessor.from_pretrained 冷启动多久（决定能不能懒加载）
  2. 冷/热分词一条 prompt 各多久（决定 WebUI 实时计数的可行性）
  3. 只传图不传文本时，processor 能否给出 image_grid_thw（决定视觉 token 能不能精确算）
"""
from __future__ import annotations

import pathlib
import sys

import paramiko

TOOLS = pathlib.Path(__file__).resolve().parent
CFG = {}
for raw in (TOOLS / "autodl_new.env").read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        CFG[k.strip()] = v.strip().strip('"').strip("'")

PY = r'''
import time, json
t0 = time.time()
from transformers import AutoProcessor
t_import = time.time() - t0

t1 = time.time()
proc = AutoProcessor.from_pretrained("/root/autodl-tmp/Qwen-Image-2.1/processor",
                                     trust_remote_code=True)
t_load = time.time() - t1
print(json.dumps({"import_s": round(t_import, 2), "processor_load_s": round(t_load, 2),
                  "class": type(proc).__name__}))

tok = proc.tokenizer
for label, text in [("short", "a red teapot on a wooden table"),
                    ("mid", "a red teapot on a wooden table, " * 200)]:
    t2 = time.time()
    n = len(tok.encode(text, add_special_tokens=False))
    print(json.dumps({label: {"chars": len(text), "tokens": n,
                              "first_call_s": round(time.time() - t2, 4)}}))
    t3 = time.time()
    n2 = len(tok.encode(text, add_special_tokens=False))
    print(json.dumps({label + "_warm": {"tokens": n2,
                                        "call_s": round(time.time() - t3, 4)}}))

# 只传图，能不能拿到 grid
from PIL import Image
import torch
img = Image.new("RGB", (1024, 1024), (120, 140, 160))
out = proc(images=[img], return_tensors="pt")
print("imageonly keys:", sorted(out.keys()))
if "image_grid_thw" in out:
    g = out["image_grid_thw"][0].tolist()
    t, h, w = g
    print(json.dumps({"image_grid_thw": g, "patch_tokens": t * h * w,
                      "merge": getattr(getattr(proc, "image_processor", None), "merge_size", None)}))

t4 = time.time()
out2 = proc(text=["<|vision_start|><|image_pad|><|vision_end|>"], images=[img],
            padding=True, padding_side="left", return_tensors="pt")
ids = out2["input_ids"][0].tolist()
tid = tok.convert_tokens_to_ids("<|image_pad|>")
print(json.dumps({"image_pad_count": ids.count(tid), "total_ids": len(ids),
                  "textplusimage_call_s": round(time.time() - t4, 4)}))
'''

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(CFG["AUTODL_HOST"], port=int(CFG["AUTODL_PORT"]), username=CFG["AUTODL_USER"],
          password=CFG["AUTODL_PASS"], timeout=25, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/_probe_proc.py", "w") as fh:
    fh.write(PY)
sftp.close()
_, out, err = c.exec_command("export PATH=/root/miniconda3/bin:$PATH; cd /root/qwen-image-2.1 && "
                             "source qwen_env.sh >/dev/null 2>&1; python /tmp/_probe_proc.py", timeout=900)
print(out.read().decode("utf-8", "replace"))
print(err.read().decode("utf-8", "replace")[-1500:])
c.close()
