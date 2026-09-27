# -*- coding: utf-8 -*-
"""在实例上量 token 数：用管线自己的 processor，而不是猜分词器。

  python tools/_tokcount.py            # 量 /tmp/promptlen_payloads.json 里的每个 prompt
  python tools/_tokcount.py --ref PATH # 顺带量参考图的视觉 token 数

输出 JSON：每个 prompt 的 instruction token 数，以及套上管线模板后的总 token 数。
管线的 prompt 模板会给消费端加上 system prompt 与 <|im_start|> 之类的包装，
所以"用户能写多长"和"编码器实际读到多长"差着一段固定开销，这里把两者分开报。
"""
from __future__ import annotations

import base64
import json
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
import json, sys
import torch
from diffusers import QwenImage21Pipeline

model_dir = "/root/autodl-tmp/Qwen-Image-2.1"
pipe = QwenImage21Pipeline.from_pretrained(model_dir, torch_dtype=torch.bfloat16,
                                           text_encoder=None, transformer=None, vae=None)
proc = pipe.processor
tok = proc.tokenizer

sys_prompt = pipe.sys_prompt
t2i_tpl = pipe.prompt_template_t2i
print("sys_prompt chars:", len(sys_prompt))
print("sys_prompt tokens:", len(tok.encode(sys_prompt, add_special_tokens=False)))

payload = json.load(open("/tmp/promptlen_payloads.json"))
out = {}
for name, text in payload.items():
    n_instr = len(tok.encode(text, add_special_tokens=False))
    wrapped = t2i_tpl.format(text)
    n_total = len(tok.encode(wrapped, add_special_tokens=False))
    out[name] = {"chars": len(text), "instruction_tokens": n_instr,
                 "wrapped_tokens": n_total, "overhead": n_total - n_instr}
print(json.dumps(out, ensure_ascii=False))

# 参考图的视觉 token 数：<image_pad> 的个数
try:
    from PIL import Image
    p = sys.argv[1] if len(sys.argv) > 1 else "/root/qwen-image-2.1/inputs/_probe_ref.jpg"
    img = Image.open(p).convert("RGB")
    for side in (512, 768, 1024, 1280):
        im = img.resize((side, side))
        ids = proc(text=["<image1><|vision_start|><|image_pad|><|vision_end|>hi"], images=[im],
                   padding=True, padding_side="left", return_tensors="pt")["input_ids"][0].tolist()
        n_pad = ids.count(tok.convert_tokens_to_ids("<|image_pad|>"))
        print(f"  ref {side}x{side}: image_pad={n_pad} tokens, total ids={len(ids)}")
except Exception as e:
    print("  ref probe failed:", type(e).__name__, str(e)[:200])
'''

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(CFG["AUTODL_HOST"], port=int(CFG["AUTODL_PORT"]), username=CFG["AUTODL_USER"],
          password=CFG["AUTODL_PASS"], timeout=25, allow_agent=False, look_for_keys=False)


def run(cmd, timeout=900):
    _, out, err = c.exec_command(cmd, timeout=timeout)
    return (out.read().decode("utf-8", "replace"),
            err.read().decode("utf-8", "replace"),
            out.channel.recv_exit_status())


run("echo %s | base64 -d > /tmp/_tok.py" % base64.b64encode(PY.encode()).decode())
o, e, rc = run("export PATH=/root/miniconda3/bin:$PATH; cd /root/qwen-image-2.1 && "
               "source qwen_env.sh >/dev/null 2>&1; python /tmp/_tok.py "
               + (sys.argv[1] if len(sys.argv) > 1 else ""), timeout=900)
print(o or e)
c.close()
