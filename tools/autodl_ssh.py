#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""SSH helper for the AutoDL instance that runs the Qwen-Image-2.1 service.

Both actions run against a fresh SSH connection (no state kept between calls):

  python tools/autodl_ssh.py run  "nvidia-smi"          # exec a shell command
  python tools/autodl_ssh.py health                     # GET /health on the box
  python tools/autodl_ssh.py fwd --script local.py      # local port-forward, then run a script

With fwd, the remote 127.0.0.1:6006 is reachable from the script as
http://127.0.0.1:<localport>. The script runs in-process via exec().

Credentials: tools/autodl.env（推荐）或 tools/autodl2.env（旧名），也可用 AUTODL_* 环境变量。
             tools/deploy_service.py --save-env 生成的就是 autodl.env。
"""
import os
import pathlib
import select
import socketserver
import sys
import threading
import time

import paramiko

# 两个都读，后者覆盖前者（保留旧名兼容；新流程统一写 autodl.env）
ENV_NAMES = ("autodl.env", "autodl2.env")
CFG = {"host": None, "port": None, "user": None, "password": None}


def load_env():
    for name in ENV_NAMES:
        envf = pathlib.Path(__file__).with_name(name)
        if not envf.exists():
            continue
        for raw in envf.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            CFG[{"AUTODL_HOST": "host", "AUTODL_PORT": "port",
                 "AUTODL_USER": "user", "AUTODL_PASS": "password"}.get(k.strip(), "?")] = v
    for env, key in (("AUTODL_HOST", "host"), ("AUTODL_PORT", "port"),
                     ("AUTODL_USER", "user"), ("AUTODL_PASS", "password")):
        if os.environ.get(env):
            CFG[key] = os.environ[env]
    CFG["port"] = int(CFG["port"])


def connect(timeout=30):
    last = None
    for kwargs in ({}, {"disabled_algorithms": {"pubkeys": ["rsa-sha2-512", "rsa-sha2-256"]}}):
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(CFG["host"], port=CFG["port"], username=CFG["user"],
                      password=CFG["password"], timeout=timeout, banner_timeout=30,
                      auth_timeout=30, allow_agent=False, look_for_keys=False, **kwargs)
            return c
        except paramiko.AuthenticationException as exc:
            last = exc
            continue
    raise last


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        chan = self.server.transport.open_channel(
            "direct-tcpip", (self.server.dst_host, self.server.dst_port), self.request.getpeername())
        if chan is None:
            return
        try:
            while True:
                r, _, _ = select.select([self.request, chan], [], [], 1.0)
                if self.request in r:
                    data = self.request.recv(65536)
                    if not data:
                        break
                    chan.sendall(data)
                if chan in r:
                    data = chan.recv(65536)
                    if not data:
                        break
                    self.request.sendall(data)
        finally:
            chan.close()


class ForwardServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def cmd_run(cmd, timeout=None):
    c = connect()
    try:
        _, out, err = c.exec_command(cmd, timeout=timeout)
        o = out.read().decode("utf-8", "replace")
        e = err.read().decode("utf-8", "replace")
        rc = out.channel.recv_exit_status()
        sys.stdout.write(o)
        if e:
            sys.stderr.write(e)
        print(f"\n[remote exit code: {rc}]")
        return rc
    finally:
        c.close()


def cmd_health():
    c = connect()
    try:
        _, out, _ = c.exec_command(
            "export PATH=/root/miniconda3/bin:$PATH; "
            "curl -s -m 8 localhost:6006/health || echo 'SERVICE_DOWN'", timeout=30)
        print(out.read().decode("utf-8", "replace"))
        print("--- gpu ---")
        _, out2, _ = c.exec_command(
            "nvidia-smi --query-gpu=name,memory.total,memory.used,driver_version,compute_cap "
            "--format=csv 2>&1 | head -5", timeout=30)
        print(out2.read().decode("utf-8", "replace"))
        print("--- service log tail ---")
        _, out3, _ = c.exec_command("tail -5 /root/qwen-image-2.1/logs/service.log 2>&1", timeout=30)
        print(out3.read().decode("utf-8", "replace"))
    finally:
        c.close()


def cmd_fwd(script_path, local_port=16006):
    """Open a local port forward to the remote 6006, then exec the local script."""
    c = connect()
    fwd = ForwardServer(("127.0.0.1", local_port), Handler)
    fwd.dst_host, fwd.dst_port = "127.0.0.1", 6006
    fwd.transport = c.get_transport()
    t = threading.Thread(target=fwd.serve_forever, daemon=True)
    t.start()
    print(f"[fwd] 127.0.0.1:{local_port} -> remote 127.0.0.1:6006 over ssh", flush=True)

    ns = {"__name__": "__main__", "BASE": f"http://127.0.0.1:{local_port}", "argv": []}
    src = pathlib.Path(script_path).read_text(encoding="utf-8")
    try:
        exec(compile(src, script_path, "exec"), ns)
    finally:
        fwd.shutdown()
        c.close()
        print("[fwd] closed", flush=True)


def main():
    load_env()
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    action = sys.argv[1]
    if action == "run":
        return cmd_run(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else None)
    if action == "health":
        return cmd_health()
    if action == "fwd":
        port = 16006
        args = sys.argv[2:]
        while args and args[0].startswith("--"):
            flag = args[0][2:]
            args = args[1:]
            if flag.startswith("port="):
                port = int(flag.split("=", 1)[1])
            elif flag == "script" and args:
                args = [args[0]] + args[1:]
        if not args:
            print("usage: autodl_ssh.py fwd [--port=16006] <local_script.py>")
            return 2
        return cmd_fwd(args[0], port)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
