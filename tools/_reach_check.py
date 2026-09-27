# -*- coding: utf-8 -*-
"""Check whether the Qwen service / WebUI is reachable, and how.

  python tools/_reach_check.py

Answers three separate questions:
  1. is the service itself alive on the instance (via SSH + local forward)
  2. does the WebUI respond with HTTP 200 for / , /ui , /docs
  3. is the public URL mapping live (AutoDL prints it in /init/others/help)

Prints no credentials.
"""
from __future__ import annotations

import pathlib
import sys
import threading
import time

import paramiko
import requests

TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import autodl_ssh  # noqa: E402

ENVF = TOOLS / "autodl_new.env"
CFG = {}
for raw in ENVF.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    CFG[k.strip()] = v.strip().strip('"').strip("'")

print(f"[ssh] target {CFG['AUTODL_HOST']}:{CFG['AUTODL_PORT']} (file {ENVF.name})")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    c.connect(CFG["AUTODL_HOST"], port=int(CFG["AUTODL_PORT"]), username=CFG["AUTODL_USER"],
              password=CFG["AUTODL_PASS"], timeout=25, banner_timeout=30, auth_timeout=30,
              allow_agent=False, look_for_keys=False)
except Exception as exc:                                                # noqa: BLE001
    print(f"[ssh] FAILED {type(exc).__name__}: {exc}")
    sys.exit(1)
print("[ssh] connected")

fwd = autodl_ssh.ForwardServer(("127.0.0.1", 16055), autodl_ssh.Handler)
fwd.dst_host, fwd.dst_port = "127.0.0.1", 6006
fwd.transport = c.get_transport()
threading.Thread(target=fwd.serve_forever, daemon=True).start()
time.sleep(0.4)
BASE = "http://127.0.0.1:16055"

try:
    h = requests.get(BASE + "/health", timeout=15).json()
    print(f"[svc] {h['status']} | model={h['model']} | mock={h['mock']} | loaded={h['loaded']}"
          f" | queue={h.get('queue_depth')} | gpu_free={(h.get('gpu') or {}).get('free_gb')}GB")
except Exception as exc:                                                # noqa: BLE001
    print(f"[svc] /health failed: {type(exc).__name__}: {exc}")

print("[webui] through the SSH tunnel (what you can do without any public entry):")
for path in ("/", "/ui", "/docs", "/v1/models"):
    try:
        r = requests.get(BASE + path, timeout=15, allow_redirects=False)
        note = "" if r.status_code != 401 else "  (needs ?key=... or Bearer)"
        print(f"   {path:<12} -> {r.status_code}  {len(r.content)} bytes{note}")
    except Exception as exc:                                            # noqa: BLE001
        print(f"   {path:<12} -> {type(exc).__name__}")

print("[public] mapping reported by the instance:")
out = c.exec_command("bash /root/qwen-image-2.1/scripts/show_url.sh 2>&1", timeout=60)[1]
print("   " + out.read().decode("utf-8", "replace").strip().replace("\n", "\n   "))
listen = c.exec_command('ss -ltn 2>/dev/null | grep -E ":6006|:6008" || '
                        'netstat -ltn 2>/dev/null | grep -E ":6006|:6008"',
                        timeout=60)[1].read().decode("utf-8", "replace").strip()
print("[bind] " + (listen or "no listener found on 6006/6008"))

fwd.shutdown()
c.close()
