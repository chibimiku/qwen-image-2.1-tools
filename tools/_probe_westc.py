# -*- coding: utf-8 -*-
"""One-off probe: is the westc clone reachable and does it run the Qwen service?

Never prints credentials. Read-only: /health, nvidia-smi, serve.sh status.
"""
import pathlib
import sys

import paramiko

ENVF = pathlib.Path(__file__).with_name("autodl_new.env")
CFG = {}
for raw in ENVF.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    CFG[k.strip()] = v.strip().strip('"').strip("'")

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    c.connect(CFG["AUTODL_HOST"], port=int(CFG["AUTODL_PORT"]), username=CFG["AUTODL_USER"],
              password=CFG["AUTODL_PASS"], timeout=25, banner_timeout=30, auth_timeout=30,
              allow_agent=False, look_for_keys=False)
except Exception as exc:  # noqa: BLE001
    print(f"[ssh] FAILED {type(exc).__name__}: {exc}")
    sys.exit(1)

print("[ssh] connected")


def run(cmd, label):
    _, out, err = c.exec_command(cmd, timeout=60)
    o = out.read().decode("utf-8", "replace")
    e = err.read().decode("utf-8", "replace")
    rc = out.channel.recv_exit_status()
    print(f"--- {label} (rc={rc}) ---")
    print(o.strip()[:4000])
    if e.strip():
        print("[stderr]", e.strip()[:1000])


run("ls -d /root/qwen-image-2.1 2>&1; hostname; uptime", "box")
run("ls /root/autodl-tmp/Qwen-Image-2.1 2>&1 | head -5; du -sh /root/autodl-tmp/Qwen-Image-2.1 2>/dev/null", "ckpt")
run("nvidia-smi --query-gpu=name,memory.total,memory.used,driver_version,compute_cap "
    "--format=csv 2>&1 | head -3", "gpu")
run("curl -s -m 8 localhost:6006/health || echo SERVICE_DOWN", "health")
run("ps aux | grep -c '[s]erver.py'", "proc")
run("tail -12 /root/qwen-image-2.1/logs/service.log 2>&1", "logtail")
run("cat /root/qwen-image-2.1/service/VERSION 2>/dev/null; "
    "md5sum /root/qwen-image-2.1/service/server.py 2>/dev/null; "
    "git -C /root/qwen-image-2.1 rev-parse HEAD 2>/dev/null", "version")
c.close()
