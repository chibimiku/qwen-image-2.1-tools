# -*- coding: utf-8 -*-
"""查 prompt 长度上限：先找硬约束，再做实测扫描。

  python tools/probe_prompt_len.py --limits          # 只查配置/位置上限（不占显存推理）
  python tools/probe_prompt_len.py --sweep           # 长度扫描（会真出图）
  python tools/probe_prompt_len.py --tokens          # 只量几个候选 prompt 的 token 数
  python tools/probe_prompt_len.py --sweep --with-ref # 带一张参考图再扫一遍
  python tools/probe_prompt_len.py --plan            # 只打印计划

测量口径：
  · token 数用实例上的 processor 真实分词（不是字数估算）
  · 参考图的视觉 token 数也实测（<image_pad> 的个数）
  · 每一档记录：token 数、显存、耗时、是否成功、输出 sha256，并留图
产出一张结果表 + JSON，落到 tools/_promptlen/。
"""
from __future__ import annotations

import argparse
import base64
import json
import pathlib
import threading
import time

import paramiko
import requests

TOOLS = pathlib.Path(__file__).resolve().parent
OUT = TOOLS / "_promptlen"
CFG = {}
for raw in (TOOLS / "autodl_new.env").read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        CFG[k.strip()] = v.strip().strip('"').strip("'")

REMOTE = "/root/qwen-image-2.1"


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(CFG["AUTODL_HOST"], port=int(CFG["AUTODL_PORT"]), username=CFG["AUTODL_USER"],
              password=CFG["AUTODL_PASS"], timeout=25, banner_timeout=30, auth_timeout=30,
              allow_agent=False, look_for_keys=False)
    return c


def run(c, cmd, timeout=900):
    _, out, err = c.exec_command(cmd, timeout=timeout)
    return (out.read().decode("utf-8", "replace"),
            err.read().decode("utf-8", "replace"),
            out.channel.recv_exit_status())


def push_py(c, src: str, remote_name: str) -> None:
    """用 SFTP 写远端文件。

    别改成 `echo <base64> | base64 -d`：payload 有几万字符，会撞 shell 参数上限，
    表现是 SSH 连接被直接掐断（paramiko 抛 EOFError），而且看起来像网络抖动。
    """
    sftp = c.open_sftp()
    try:
        with sftp.file(f"/tmp/{remote_name}", "w") as fh:
            fh.write(src)
    finally:
        sftp.close()


LIMITS_PY = r'''
import json, os
import torch
from transformers import AutoProcessor, AutoConfig

model_dir = "/root/autodl-tmp/Qwen-Image-2.1"
print("== config ==")
try:
    cfg = AutoConfig.from_pretrained(model_dir, trust_remote_code=True)
    for k in ("text_encoder", "text_encoder_config", "tokenizer_max_length", "max_position_embeddings"):
        if hasattr(cfg, k):
            v = getattr(cfg, k)
            print(f"  top.{k}: {str(v)[:200]}")
    print("  top keys:", [k for k in list(cfg.to_dict().keys()) if "text" in k or "tok" in k][:12])
except Exception as e:
    print("  config failed:", type(e).__name__, e)

print("== text encoder config ==")
for sub in ("text_encoder", "text_encoder_2"):
    p = os.path.join(model_dir, sub)
    if not os.path.isdir(p):
        continue
    try:
        tc = AutoConfig.from_pretrained(p, trust_remote_code=True)
        d = tc.to_dict()
        keys = [k for k in d if any(s in k for s in ("max_position", "rope", "seq", "token", "mrope"))]
        for k in keys:
            print(f"  {sub}.{k}: {str(d[k])[:160]}")
        print(f"  {sub}.model_type:", d.get("model_type"))
        # 文本塔的实际层配置往往在嵌套里
        for nest in ("text_config", "language_config", "llm_config"):
            if nest in d and isinstance(d[nest], dict):
                nd = d[nest]
                for k in [k for k in nd if any(s in k for s in ("max_position", "rope", "seq"))]:
                    print(f"  {sub}.{nest}.{k}: {str(nd[k])[:160]}")
    except Exception as e:
        print(f"  {sub} failed:", type(e).__name__, e)
        print("   files:", sorted(os.listdir(p))[:12])

print("== tokenizer ==")
try:
    proc = AutoProcessor.from_pretrained(model_dir, trust_remote_code=True)
    tok = proc.tokenizer
    print("  tokenizer class:", type(tok).__name__)
    print("  len(tokenizer):", len(tok))
    print("  model_max_length:", getattr(tok, "model_max_length", None))
    for probe in ["one red teapot on a wooden table"]:
        ids = tok.encode(probe)
        print(f"  sample '{probe[:30]}...' -> {len(ids)} tokens")
except Exception as e:
    print("  processor failed:", type(e).__name__, e)
'''


TOKENS_PY = r'''
import json, os
import importlib
res = {}

def try_load(desc, fn):
    try:
        obj = fn()
        res[desc] = "ok"
        return obj
    except Exception as e:
        res[desc] = f"{type(e).__name__}: {str(e)[:120]}"
        return None

model_dir = "/root/autodl-tmp/Qwen-Image-2.1"
from transformers import AutoTokenizer

tok = None
for desc, path in (("text_encoder", os.path.join(model_dir, "text_encoder")),
                   ("tokenizer", os.path.join(model_dir, "tokenizer"))):
    if os.path.isdir(path):
        files = sorted(os.listdir(path))
        res[desc + "_files"] = files[:20]
        tok = tok or try_load(desc, lambda p=path: AutoTokenizer.from_pretrained(p, trust_remote_code=True))

# 拿 pipeline 用的那个 processor 更准：它带 tokenizer
if tok is None:
    for mod in ("diffusers",):
        try:
            m = importlib.import_module(mod)
            P = getattr(m, "QwenImage21Processor", None)
            if P:
                proc = P.from_pretrained(model_dir)
                tok = proc.tokenizer
                res["processor"] = "ok"
                break
        except Exception as e:
            res["processor"] = f"{type(e).__name__}: {str(e)[:160]}"

if tok is None:
    print(json.dumps({"error": "no tokenizer", "detail": res}, ensure_ascii=False))
    raise SystemExit(0)

res["tokenizer_class"] = type(tok).__name__
res["model_max_length"] = getattr(tok, "model_max_length", None)
res["vocab"] = len(tok)

payload = json.load(open("/tmp/promptlen_payloads.json"))
counts = {}
for name, text in payload.items():
    counts[name] = len(tok.encode(text))
print(json.dumps({"counts": counts, "info": res}, ensure_ascii=False))
'''


REF_TOKENS_PY = r'''
import json
import torch
from PIL import Image
from transformers import AutoProcessor
model_dir = "/root/autodl-tmp/Qwen-Image-2.1"
proc = None
for cls_name in ("AutoProcessor",):
    proc = AutoProcessor.from_pretrained(model_dir, trust_remote_code=True)
img = Image.open("/root/qwen-image-2.1/inputs/_probe_ref.jpg").convert("RGB")
for side in (512, 1024):
    im = img.resize((side, side))
    out = proc(text=["<image1><|vision_start|><|image_pad|><|vision_end|>hi"], images=[im],
               padding=True, padding_side="left", return_tensors="pt")
    ids = out["input_ids"][0].tolist()
    n_pad = ids.count(proc.tokenizer.convert_tokens_to_ids("<|image_pad|>"))
    print(f"  {side}x{side} -> image_pad tokens = {n_pad}, total ids = {len(ids)}")
'''


def build_payloads(levels: list[int]) -> dict:
    """按目标 token 数生成同一句话的重复文本。

    实测标定：这份模板下 1 token ≈ 4.07 字符，所以按字符给量，
    再在扫描结果里回报真实 token 数（用 _tokcount.py 量）。
    末尾固定追加一句不同的收尾描述，出图应随之变化，用来判断长文本有没有被读到。
    """
    base = ("a red ceramic teapot on a wooden table, next to a blue cup and two yellow lemons, "
            "window light from the left. ")
    tail = " In the far background stands a small white lighthouse."
    payloads = {}
    for n in levels:
        target_chars = int(n * 4.07)
        reps = max(1, target_chars // len(base))
        payloads[f"T{n}"] = base * reps + tail
    return payloads



def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limits", action="store_true", help="查配置里的位置上限")
    ap.add_argument("--tokens", action="store_true", help="量候选 prompt 的 token 数")
    ap.add_argument("--sweep", action="store_true", help="做长度扫描")
    ap.add_argument("--with-ref", action="store_true", help="带参考图再扫一遍")
    ap.add_argument("--plan", action="store_true", help="只打印计划")
    ap.add_argument("--levels", default="100,400,1000,2000,3000,4000",
                    help="目标 token 档位（逗号分隔）")
    a = ap.parse_args()

    levels = [int(x) for x in a.levels.split(",") if x]
    plan = {"levels_tokens": levels, "with_ref": a.with_ref,
            "note": ("每档把同一句可验证的话重复到接近目标 token 数；"
                     "记录实际 token 数、耗时、显存、输出 sha256")}
    if a.plan:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    OUT.mkdir(exist_ok=True)
    c = connect()

    if a.limits:
        push_py(c, LIMITS_PY, "pl_limits.py")
        o, e, rc = run(c, "export PATH=/root/miniconda3/bin:$PATH; cd /root/qwen-image-2.1 && "
                          "source qwen_env.sh >/dev/null 2>&1; python /tmp/pl_limits.py 2>&1", timeout=600)
        print(o or e)
        (OUT / "limits.txt").write_text(o + e, encoding="utf-8")
        c.close()
        return 0

    payloads = build_payloads(levels)
    push_py(c, json.dumps(payloads, ensure_ascii=False), "promptlen_payloads.json")

    if a.tokens:
        push_py(c, TOKENS_PY, "pl_tokens.py")
        o, e, rc = run(c, "export PATH=/root/miniconda3/bin:$PATH; cd /root/qwen-image-2.1 && "
                          "source qwen_env.sh >/dev/null 2>&1; python /tmp/pl_tokens.py 2>&1",
                       timeout=600)
        print(o or e)
        (OUT / "token-counts.json").write_text(o + e, encoding="utf-8")
        push_py(c, REF_TOKENS_PY, "pl_ref.py")
        mkc = ("mkdir -p /root/qwen-image-2.1/inputs && "
               "/root/miniconda3/bin/python -c \""
               "from PIL import Image; Image.new('RGB',(1280,1280),(120,140,160))"
               ".save('/root/qwen-image-2.1/inputs/_probe_ref.jpg')\"")
        o3, e3, _ = run(c, mkc, timeout=120)
        print("  建参考图:", (o3 or e3).strip() or "ok")
        o2, e2, _ = run(c, "export PATH=/root/miniconda3/bin:$PATH; cd /root/qwen-image-2.1 && "
                           "source qwen_env.sh >/dev/null 2>&1; python /tmp/pl_ref.py 2>&1", timeout=900)
        print("== 参考图的视觉 token 数 ==")
        print(o2 or e2)
        c.close()
        return 0

    if a.sweep:
        rows = sweep(c, payloads, with_ref=a.with_ref)
        (OUT / ("sweep-withref.json" if a.with_ref else "sweep.json")).write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        c.close()
        return 0

    print(json.dumps(plan, ensure_ascii=False, indent=2))
    c.close()
    return 0


def sweep(c, payloads: dict, with_ref: bool = False) -> list[dict]:
    """逐档真出图：记录 token 数、显存、耗时、结果。"""
    key = ""
    for line in (TOOLS / ".qwenkey").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.strip().startswith("#"):
            key = line.strip()
            break
    sys_path = str(TOOLS)
    import sys as _s
    if sys_path not in _s.path:
        _s.path.insert(0, sys_path)
    import autodl_ssh
    import requests as rq

    fwd = autodl_ssh.ForwardServer(("127.0.0.1", 16055), autodl_ssh.Handler)
    fwd.dst_host, fwd.dst_port = "127.0.0.1", 6006
    fwd.transport = c.get_transport()
    threading.Thread(target=fwd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    base = "http://127.0.0.1:16055"
    hdr = {"Authorization": f"Bearer {key}"}
    rows = []
    ref = TOOLS / "_promptlen" / "ref.jpg"
    try:
        for name, text in payloads.items():
            o, _, _ = run(c, "nvidia-smi --query-gpu=memory.free --format=csv,noheader", timeout=60)
            free0 = o.strip()
            body = {"prompt": text, "width": 1024, "height": 1024,
                    "num_inference_steps": 40, "true_cfg_scale": 1.0,
                    "output_format": "png", "num_images_per_prompt": 1,
                    "anatomy_check": False, "seed": 4242}
            t0 = time.time()
            rec = {"level": name, "chars": len(text), "gpu_free_before": free0,
                   "with_ref": with_ref}
            try:
                if with_ref and ref.exists():
                    with open(ref, "rb") as fh:
                        files = [("image", (ref.name, fh, "image/jpeg"))]
                        r = rq.post(base + "/v1/images/generations", data=body, files=files,
                                    headers=hdr, timeout=(30, 1800))
                else:
                    r = rq.post(base + "/v1/images/generations", json=body, headers=hdr,
                                timeout=(30, 1800))
                rec["http"] = r.status_code
                rec["elapsed_s"] = round(time.time() - t0, 2)
                if r.status_code == 200:
                    item = r.json()["data"][0]
                    img = base64.b64decode(item["b64_json"])
                    import hashlib
                    rec["png_bytes"] = len(img)
                    rec["sha256"] = hashlib.sha256(img).hexdigest()[:16]
                    rec["seed"] = item.get("seed")
                    (OUT / f"{'ref' if with_ref else 't2i'}-{name}.png").write_bytes(img)
                    rec["ok"] = True
                else:
                    rec["ok"] = False
                    rec["error"] = r.text[:400]
            except Exception as exc:                                    # noqa: BLE001
                rec["ok"] = False
                rec["elapsed_s"] = round(time.time() - t0, 2)
                rec["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
            o2, _, _ = run(c, "nvidia-smi --query-gpu=memory.free --format=csv,noheader", timeout=60)
            rec["gpu_free_after"] = o2.strip()
            print(json.dumps(rec, ensure_ascii=False))
            rows.append(rec)
    finally:
        fwd.shutdown()
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
