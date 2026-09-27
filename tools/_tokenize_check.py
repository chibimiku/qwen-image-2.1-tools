# -*- coding: utf-8 -*-
"""实测 /v1/tokenize：数值必须和管线自己的 processor 对得上。

  python tools/_tokenize_check.py

对照口径（都走同一个 tokenizer，所以应该完全相等，不是"接近"）：
  · instruction_tokens  vs  tok.encode(prompt)
  · wrapped_tokens      vs  tok.encode(pipeline.prompt_template_t2i.format(prompt))
  · vision_tokens       vs  processor(images=[1024²]) 里 <|image_pad|> 的个数
另外验证鉴权、超限判定、以及"带参考图时预算被吃掉"这个语义。
"""
from __future__ import annotations

import json
import pathlib
import sys
import threading
import time

import paramiko
import requests

TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import autodl_ssh  # noqa: E402

CFG = {}
for raw in (TOOLS / "autodl_new.env").read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        CFG[k.strip()] = v.strip().strip('"').strip("'")

REF_PY = r'''
import json, sys
import torch
from diffusers import QwenImage21Pipeline

pipe = QwenImage21Pipeline.from_pretrained("/root/autodl-tmp/Qwen-Image-2.1",
                                           torch_dtype=torch.bfloat16,
                                           text_encoder=None, transformer=None, vae=None)
tok = pipe.processor.tokenizer
# 从文件读，别当 CLI 参数传：长 prompt 会撞 shell 参数上限（ARG_MAX）
text = open("/tmp/_tok_text.txt", encoding="utf-8").read()
print(json.dumps({
    "instruction": len(tok.encode(text, add_special_tokens=False)),
    "wrapped_t2i": len(tok.encode(pipe.prompt_template_t2i.format(text), add_special_tokens=False)),
    "wrapped_ti2i": len(tok.encode(pipe.prompt_template_ti2i.format(text), add_special_tokens=False)),
    "sys_prompt_tokens": len(tok.encode(pipe.sys_prompt, add_special_tokens=False)),
}))
'''


def key() -> str:
    for line in (TOOLS / ".qwenkey").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.strip().startswith("#"):
            return line.strip()
    return ""


def main() -> int:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(CFG["AUTODL_HOST"], port=int(CFG["AUTODL_PORT"]), username=CFG["AUTODL_USER"],
              password=CFG["AUTODL_PASS"], timeout=25, allow_agent=False, look_for_keys=False)

    def sh(cmd, t=900):
        _, o, e = c.exec_command(cmd, timeout=t)
        return o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")

    sftp = c.open_sftp()
    with sftp.file("/tmp/_ref_tok.py", "w") as fh:
        fh.write(REF_PY)
    sftp.close()

    fwd = autodl_ssh.ForwardServer(("127.0.0.1", 16063), autodl_ssh.Handler)
    fwd.dst_host, fwd.dst_port = "127.0.0.1", 6006
    fwd.transport = c.get_transport()
    threading.Thread(target=fwd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    base = "http://127.0.0.1:16063"
    hdr = {"Authorization": "Bearer " + key()}

    fails = []

    def check(cond, label, extra=""):
        print(("  OK   " if cond else "  FAIL ") + label + (("  " + extra) if extra else ""))
        if not cond:
            fails.append(label)

    print("=== 鉴权 ===")
    try:
        r = requests.post(base + "/v1/tokenize", json={"prompt": "hi"}, timeout=60)
        check(r.status_code == 401, "不带 key -> 401", f"got {r.status_code}")
    except Exception as exc:                                            # noqa: BLE001
        check(False, "不带 key 的探测", type(exc).__name__)

    print("=== 数值对照 ===")
    samples = [
        ("短句", "a red teapot on a wooden table"),
        ("中等", "a red ceramic teapot on a wooden table, next to a blue cup and two yellow lemons, "
                 "window light from the left. " * 50),
        ("中文", "一只红色的陶瓷茶壶放在木桌上，旁边有一个蓝色的杯子和两个黄色的柠檬，左侧有窗光。"),
    ]
    for label, text in samples:
        # 文本走 SFTP 落文件，避免长 prompt 撞 shell 参数上限
        sftp = c.open_sftp()
        with sftp.file("/tmp/_tok_text.txt", "w") as fh:
            fh.write(text)
        sftp.close()
        raw = sh("export PATH=/root/miniconda3/bin:$PATH; cd /root/qwen-image-2.1 && "
                 "source qwen_env.sh >/dev/null 2>&1; python /tmp/_ref_tok.py")
        lines = [ln for ln in raw.splitlines() if ln.strip().startswith("{")]
        if not lines:
            check(False, f"{label} 直接分词失败", raw.strip()[-200:])
            continue
        rd = json.loads(lines[-1])
        r = requests.post(base + "/v1/tokenize", json={"prompt": text, "t2i": True},
                          headers=hdr, timeout=120)
        d = r.json()
        check(d["instruction_tokens"] == rd["instruction"],
              f"{label} instruction_tokens", f'api={d["instruction_tokens"]} direct={rd["instruction"]}')
        check(d["wrapped_tokens"] == rd["wrapped_t2i"],
              f"{label} wrapped_tokens(t2i)", f'api={d["wrapped_tokens"]} direct={rd["wrapped_t2i"]}')
        if label == "短句":
            check(d["chars"] == len(text), "chars 正确", f'{d["chars"]}')
            check(d["sys_prompt_tokens"] == rd["sys_prompt_tokens"],
                  "sys_prompt_tokens 取自管线", f'api={d["sys_prompt_tokens"]} direct={rd["sys_prompt_tokens"]}')
            print(f"       wrap 明细: templates t2i={rd['wrapped_t2i']} ti2i={rd['wrapped_ti2i']}, "
                  f"overhead={d['template_overhead_tokens']}")

        # 编辑模板（不带 t2i 标志）
        r2 = requests.post(base + "/v1/tokenize", json={"prompt": text}, headers=hdr, timeout=120)
        d2 = r2.json()
        check(d2["wrapped_tokens"] == rd["wrapped_ti2i"],
              f"{label} wrapped_tokens(ti2i)", f'api={d2["wrapped_tokens"]} direct={rd["wrapped_ti2i"]}')

    print("=== vision token ===")
    for side in (512, 1024):
        r = requests.post(base + "/v1/tokenize",
                          json={"prompt": "hi", "width": side, "height": side},
                          headers=hdr, timeout=180)
        d = r.json()
        vd = d.get("vision_detail") or {}
        expect = {512: 256, 1024: 1024}[side]
        check(d["vision_tokens"] == expect, f"{side}² 参考图 -> {expect} vision token",
              f'api={d["vision_tokens"]} grid={vd.get("grid")} patches={vd.get("patch_tokens")}')
        check(d["total_positions"] == d["wrapped_tokens"] + d["vision_tokens"],
              f"{side}² total = 文本 + 视觉")

    print("=== 超限判定 ===")
    # 用例自校准：先量出管线自己的直接分词结果，再由它推出期望的布尔值。
    # 不手估 token 数——重复段落不是线性增长（实测 900×base=8123，1000×base=9023），
    # 手估写期望值只会把自己的错算成接口的错。
    cases = [
        ("短", "a teapot", None),
        ("长但安全", "a red teapot on a wooden table, " * 900, None),
        ("超安全线未超上限", "a red teapot on a wooden table, " * 1000, None),
        ("超上限", "a red teapot on a wooden table, " * 2000, None),
        ("带图占预算", "a red teapot on a wooden table, " * 1000, (1024, 1024)),
    ]
    max_pos, safe_pos = 9216, 9000
    for label, text, wh in cases:
        sftp = c.open_sftp()
        with sftp.file("/tmp/_tok_text.txt", "w") as fh:
            fh.write(text)
        sftp.close()
        raw = sh("export PATH=/root/miniconda3/bin:$PATH; cd /root/qwen-image-2.1 && "
                 "source qwen_env.sh >/dev/null 2>&1; python /tmp/_ref_tok.py")
        lines = [ln for ln in raw.splitlines() if ln.strip().startswith("{")]
        if not lines:
            check(False, f"{label} 直接分词失败", raw.strip()[-160:])
            continue
        direct = json.loads(lines[-1])["wrapped_t2i"]
        vis = {512: 256, 1024: 1024}[(wh or (0, 0))[0]] if wh else 0
        want_total = direct + vis
        want_over = want_total > max_pos
        want_safe = want_total > safe_pos

        body = {"prompt": text, "t2i": True}
        if wh:
            body["width"], body["height"] = wh
        d = requests.post(base + "/v1/tokenize", json=body, headers=hdr, timeout=180).json()
        msg = (f'api={d["total_positions"]} 期望={want_total} '
               f'over={d["over_limit"]}(期望 {want_over}) '
               f'safe_over={d["over_safe"]}(期望 {want_safe})')
        check(d["total_positions"] == want_total and d["over_limit"] == want_over
              and d["over_safe"] == want_safe, label, msg)

    print()
    print(f"结论: {'通过' if not fails else '%d 项失败' % len(fails)}")
    for f in fails:
        print("   -", f)
    fwd.shutdown()
    try:
        c.close()
    except Exception:                                                   # noqa: BLE001
        pass
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
