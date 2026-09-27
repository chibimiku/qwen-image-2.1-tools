# -*- coding: utf-8 -*-
"""One-off: open a forward to the westc clone's 6006 and verify auth works.

Prints no credentials. BASE=http://127.0.0.1:16006
"""
import base64
import json
import pathlib
import sys
import threading

import paramiko
import requests

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import autodl_ssh  # noqa: E402

ENVF = pathlib.Path(__file__).with_name("autodl_new.env")
CFG = {}
for raw in ENVF.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    CFG[k.strip()] = v.strip().strip('"').strip("'")

KEY = ""
for raw in pathlib.Path(__file__).with_name(".qwenkey").read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line and not line.startswith("#"):
        KEY = line
        break
print(f"[key] loaded from tools/.qwenkey (len={len(KEY)})")

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(CFG["AUTODL_HOST"], port=int(CFG["AUTODL_PORT"]), username=CFG["AUTODL_USER"],
          password=CFG["AUTODL_PASS"], timeout=25, banner_timeout=30, auth_timeout=30,
          allow_agent=False, look_for_keys=False)
fwd = autodl_ssh.ForwardServer(("127.0.0.1", 16006), autodl_ssh.Handler)
fwd.dst_host, fwd.dst_port = "127.0.0.1", 6006
fwd.transport = c.get_transport()
threading.Thread(target=fwd.serve_forever, daemon=True).start()
print("[fwd] 127.0.0.1:16006 -> westc:6006")

BASE = "http://127.0.0.1:16006"
H = {"Authorization": f"Bearer {KEY}"}

r = requests.get(f"{BASE}/health", timeout=20)
print("health", r.status_code, r.json().get("mock"), r.json().get("model"))

r = requests.get(f"{BASE}/v1/models", headers=H, timeout=20)
print("models no-key-ok?", r.status_code)
if r.status_code == 200:
    print("  ", r.text[:200])

r2 = requests.get(f"{BASE}/v1/models", timeout=20)
print("models without key ->", r2.status_code, "(expect 401)")

r3 = requests.get(f"{BASE}/v1/models", headers={"Authorization": "Bearer WRONG"}, timeout=20)
print("models with wrong key ->", r3.status_code, "(expect 401)")

fwd.shutdown()
c.close()
