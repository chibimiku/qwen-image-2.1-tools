# -*- coding: utf-8 -*-
"""带参考图时的长度预算：验证 vision token 是否真的挤占同一份 9216 名额。

  python tools/_len_withref.py 7000 8300

假设：joint sequence = 文本 token + 视觉 token ≤ 9216（RoPE 表长）。
若是，则带一张 1024² 参考图（1024 个 vision token）时，
文本上限应从 ~9100 降到 ~8100 左右。

每档独立跑，失败后重启清上下文（越界会弄坏 CUDA context）。
"""
from __future__ import annotations

import base64
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

BASE = ("a red ceramic teapot on a wooden table, next to a blue cup and two yellow lemons, "
        "window light from the left. ")
TAIL = " In the far background stands a small white lighthouse."


def key() -> str:
    for line in (TOOLS / ".qwenkey").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.strip().startswith("#"):
            return line.strip()
    return ""


def main() -> int:
    levels = [int(x) for x in sys.argv[1:]] or [7000, 8300]
    ref = TOOLS / "_promptlen" / "ref.jpg"

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(CFG["AUTODL_HOST"], port=int(CFG["AUTODL_PORT"]), username=CFG["AUTODL_USER"],
              password=CFG["AUTODL_PASS"], timeout=25, allow_agent=False, look_for_keys=False)

    def sh(cmd, t=600):
        _, o, e = c.exec_command(cmd, timeout=t)
        return (o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")).strip()

    rows = []
    for lvl in levels:
        if sh('curl -s -m 5 -o /dev/null -w "%{http_code}" localhost:6006/health') != "200":
            sh("bash /root/qwen-image-2.1/scripts/serve.sh restart 2>&1 | tail -1", 300)
            time.sleep(25)

        text = BASE * max(1, int(lvl * 4.075) // len(BASE)) + TAIL
        rec = {"text_target_tokens": lvl, "text_chars": len(text), "ref_vision_tokens": 1024}
        fwd = autodl_ssh.ForwardServer(("127.0.0.1", 16061), autodl_ssh.Handler)
        fwd.dst_host, fwd.dst_port = "127.0.0.1", 6006
        fwd.transport = c.get_transport()
        threading.Thread(target=fwd.serve_forever, daemon=True).start()
        time.sleep(0.4)
        t0 = time.time()
        try:
            with open(ref, "rb") as fh:
                r = requests.post("http://127.0.0.1:16061/v1/images/generations",
                                  data={"prompt": text, "width": "1024", "height": "1024",
                                        "num_inference_steps": "40", "true_cfg_scale": "1.0",
                                        "output_format": "png", "seed": "4242"},
                                  files=[("image", (ref.name, fh, "image/jpeg"))],
                                  headers={"Authorization": "Bearer " + key()},
                                  timeout=(30, 1800))
            rec["http"] = r.status_code
            rec["elapsed_s"] = round(time.time() - t0, 2)
            if r.status_code == 200:
                img = base64.b64decode(r.json()["data"][0]["b64_json"])
                rec["ok"] = True
                rec["png_bytes"] = len(img)
                (TOOLS / "_promptlen" / f"withref-{lvl}.png").write_bytes(img)
            else:
                rec["ok"] = False
                rec["error"] = r.text[:200]
        except Exception as exc:                                        # noqa: BLE001
            rec["ok"] = False
            rec["elapsed_s"] = round(time.time() - t0, 2)
            rec["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        finally:
            try:
                fwd.shutdown()
            except Exception:                                           # noqa: BLE001
                pass

        if not rec.get("ok"):
            sh("bash /root/qwen-image-2.1/scripts/serve.sh restart 2>&1 | tail -1", 300)
            rec["restarted"] = True
            time.sleep(25)
        print(json.dumps(rec, ensure_ascii=False))
        rows.append(rec)

    (TOOLS / "_promptlen" / "withref.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
