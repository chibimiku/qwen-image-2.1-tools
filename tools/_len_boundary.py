# -*- coding: utf-8 -*-
"""逐档单跑 prompt 长度上限，失败后自动重启服务清掉坏掉的 CUDA 上下文。

  python tools/_len_boundary.py 9500 10000 11000 12000 14000 16000

为什么单档跑而不一次扫多档：越界会让 CUDA 抛 device-side assert，**并且把上下文弄坏**，
之后连 /health 都 500。一次扫多档会在第一个失败点之后全部失败，读不出后续数据。
所以每档独立，失败就重启服务再继续。

输出一行一档，最后打印边界结论。
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

BASE = ("a red ceramic teapot on a wooden table, next to a blue cup and two yellow lemons, "
        "window light from the left. ")
TAIL = " In the far background stands a small white lighthouse."
LOCAL_PORT = 16057


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(CFG["AUTODL_HOST"], port=int(CFG["AUTODL_PORT"]), username=CFG["AUTODL_USER"],
              password=CFG["AUTODL_PASS"], timeout=25, banner_timeout=30, auth_timeout=30,
              allow_agent=False, look_for_keys=False)
    return c


def sh(c, cmd, t=600):
    _, o, e = c.exec_command(cmd, timeout=t)
    return (o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")).strip()


def healthy(c, tries=18) -> bool:
    for _ in range(tries):
        if sh(c, 'curl -s -m 5 -o /dev/null -w "%{http_code}" localhost:6006/health') == "200":
            return True
        time.sleep(10)
    return False


def restart(c) -> bool:
    sh(c, "bash /root/qwen-image-2.1/scripts/serve.sh restart 2>&1 | tail -2", t=300)
    return healthy(c)


def key() -> str:
    for line in (TOOLS / ".qwenkey").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.strip().startswith("#"):
            return line.strip()
    return ""


def sanity(c) -> bool:
    """小图快速出图，证明上下文是干净的。坏掉的上下文会让连短 prompt 都失败。"""
    fwd = autodl_ssh.ForwardServer(("127.0.0.1", 16059), autodl_ssh.Handler)
    fwd.dst_host, fwd.dst_port = "127.0.0.1", 6006
    fwd.transport = c.get_transport()
    threading.Thread(target=fwd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    try:
        r = requests.post("http://127.0.0.1:16059/v1/images/generations",
                          json={"prompt": "one red teapot on a wooden table", "width": 512,
                                "height": 512, "num_inference_steps": 8, "output_format": "png",
                                "seed": 7},
                          headers={"Authorization": "Bearer " + key()}, timeout=(30, 300))
        return r.status_code == 200
    except Exception:                                                   # noqa: BLE001
        return False
    finally:
        try:
            fwd.shutdown()
        except Exception:                                               # noqa: BLE001
            pass


def main() -> int:
    levels = [int(x) for x in sys.argv[1:]] or [9000, 9200, 9300, 9400, 9500]
    c = connect()
    print(f"[gpu] {sh(c, 'nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader')}")

    rows = []
    for lvl in levels:
        # 每档开始前保证服务是干净的：上次越界会把上下文弄坏，坏上下文下所有档都会"失败"
        if not healthy(c, tries=2):
            print("  [svc] 不健康，重启")
            restart(c)
        if not sanity(c):
            print("  [svc] sanity 失败，重启后再试")
            restart(c)
            if not sanity(c):
                print("  [svc] 重启后 sanity 仍失败，放弃")
                break

        text = BASE * max(1, int(lvl * 4.075) // len(BASE)) + TAIL
        rec = {"target_tokens": lvl, "chars": len(text)}

        fwd = autodl_ssh.ForwardServer(("127.0.0.1", LOCAL_PORT), autodl_ssh.Handler)
        fwd.dst_host, fwd.dst_port = "127.0.0.1", 6006
        fwd.transport = c.get_transport()
        threading.Thread(target=fwd.serve_forever, daemon=True).start()
        time.sleep(0.4)
        base = f"http://127.0.0.1:{LOCAL_PORT}"

        t0 = time.time()
        try:
            r = requests.post(base + "/v1/images/generations",
                              json={"prompt": text, "width": 1024, "height": 1024,
                                    "num_inference_steps": 40, "true_cfg_scale": 1.0,
                                    "output_format": "png", "num_images_per_prompt": 1,
                                    "anatomy_check": False, "seed": 4242},
                              headers={"Authorization": "Bearer " + key()},
                              timeout=(30, 1800))
            rec["http"] = r.status_code
            rec["elapsed_s"] = round(time.time() - t0, 2)
            if r.status_code == 200:
                import base64 as b64
                img = b64.b64decode(r.json()["data"][0]["b64_json"])
                rec["png_bytes"] = len(img)
                rec["ok"] = True
                (TOOLS / "_promptlen").mkdir(exist_ok=True)
                (TOOLS / "_promptlen" / f"bound-{lvl}.png").write_bytes(img)
            else:
                rec["ok"] = False
                rec["error"] = r.text[:200]
        except Exception as exc:                                        # noqa: BLE001
            rec["ok"] = False
            rec["elapsed_s"] = round(time.time() - t0, 2)
            rec["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        finally:
            try:
                fwd.shutdown()
            except Exception:                                           # noqa: BLE001
                pass

        if not rec.get("ok"):
            rec["health_after"] = sh(c, 'curl -s -m 8 localhost:6006/health | head -c 100')[:100]
            print("  -> 失败，重启服务清上下文…")
            rec["restarted"] = restart(c)
        print(json.dumps(rec, ensure_ascii=False))
        rows.append(rec)
        time.sleep(2)

    ok = [r["target_tokens"] for r in rows if r.get("ok")]
    bad = [r["target_tokens"] for r in rows if not r.get("ok")]
    print(f"\n通过: {ok}\n失败: {bad}")
    if ok and bad:
        print(f"边界落在 {max(ok)} 与 {min(bad)} 之间（目标 token 数）")
    (TOOLS / "_promptlen").mkdir(exist_ok=True)
    (TOOLS / "_promptlen" / "boundary.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
