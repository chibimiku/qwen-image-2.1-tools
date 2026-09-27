# -*- coding: utf-8 -*-
"""一次算清：候选 prompt 的字符数 + 精确 token 数 + 参考图视觉 token 数。

  python tools/_calibrate_len.py                 # 用默认档位
  python tools/_calibrate_len.py 6000 7500 8500  # 指定目标 token 数

把 payload 写到实例 /tmp/promptlen_payloads.json，再用管线自己的 processor 量 token。
输出一张干净的对照表，用来把"字符数"换算成"token 数"，以及算 prompt+参考图的合计 token。
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

BASE = ("a red ceramic teapot on a wooden table, next to a blue cup and two yellow lemons, "
        "window light from the left. ")
TAIL = " In the far background stands a small white lighthouse."

PY = r'''
import json
import torch
from diffusers import QwenImage21Pipeline

pipe = QwenImage21Pipeline.from_pretrained("/root/autodl-tmp/Qwen-Image-2.1",
                                           torch_dtype=torch.bfloat16,
                                           text_encoder=None, transformer=None, vae=None)
tok = pipe.processor.tokenizer
tpl = pipe.prompt_template_t2i
payload = json.load(open("/tmp/promptlen_payloads.json"))
rows = []
for name, text in payload.items():
    n_i = len(tok.encode(text, add_special_tokens=False))
    n_w = len(tok.encode(tpl.format(text), add_special_tokens=False))
    rows.append({"name": name, "chars": len(text), "chars_per_token": round(len(text) / n_i, 3),
                 "instruction_tokens": n_i, "wrapped_tokens": n_w, "overhead": n_w - n_i})
print(json.dumps({"rows": rows, "sys_prompt_tokens": len(tok.encode(pipe.sys_prompt, add_special_tokens=False))},
                 ensure_ascii=False))
'''


def main() -> int:
    levels = [int(x) for x in sys.argv[1:]] or [1000, 4000, 6000, 7500, 8000, 8500, 8800, 9000]
    payloads = {}
    for n in levels:
        reps = max(1, int(n * 4.07) // len(BASE))
        payloads[f"T{n}"] = BASE * reps + TAIL

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(CFG["AUTODL_HOST"], port=int(CFG["AUTODL_PORT"]), username=CFG["AUTODL_USER"],
              password=CFG["AUTODL_PASS"], timeout=25, allow_agent=False, look_for_keys=False)

    def run(cmd, t=900):
        _, o, e = c.exec_command(cmd, timeout=t)
        return o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")

    # 用 SFTP 写文件：payload 有几万字符，走 `echo | base64 -d` 会撞 shell 参数上限并掐断连接
    sftp = c.open_sftp()
    with sftp.file("/tmp/promptlen_payloads.json", "w") as fh:
        fh.write(json.dumps(payloads, ensure_ascii=False))
    with sftp.file("/tmp/_cal.py", "w") as fh:
        fh.write(PY)
    sftp.close()
    out = run("export PATH=/root/miniconda3/bin:$PATH; cd /root/qwen-image-2.1 && "
              "source qwen_env.sh >/dev/null 2>&1; python /tmp/_cal.py")
    c.close()

    line = [ln for ln in out.splitlines() if ln.strip().startswith("{")]
    if not line:
        print(out)
        return 1
    data = json.loads(line[-1])
    print(f"system prompt 本身: {data['sys_prompt_tokens']} tokens（模板固定开销，与用户输入无关）\n")
    print(f"{'档位':<8}{'字符数':>8}{'字符/token':>12}{'指令token':>11}{'含模板':>9}{'固定开销':>9}")
    for r in data["rows"]:
        print(f"{r['name']:<8}{r['chars']:>8}{r['chars_per_token']:>12}{r['instruction_tokens']:>11}"
              f"{r['wrapped_tokens']:>9}{r['overhead']:>9}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
