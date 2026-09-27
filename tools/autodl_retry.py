#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""SSH runner with retry/backoff.

Why this exists: the AutoDL gateway intermittently drops the TCP connection
right after accept (``Error reading SSH protocol banner``), and
``tools/autodl_run.py`` treats that as fatal.  This wrapper retries the
*handshake* several times with backoff, so multi-minute remote jobs (model
downloads) survive a flaky gateway.

Usage:
  python tools/autodl_retry.py "nvidia-smi"
  python tools/autodl_retry.py --file remote/scripts/_x.sh
  python tools/autodl_retry.py --timeout 1800 "long command"
  python tools/autodl_retry.py --put local remote
  python tools/autodl_retry.py --get remote local
"""
from __future__ import annotations

import os
import pathlib
import socket
import sys
import time

import paramiko

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import autodl_run  # noqa: E402  (reuses credentials loading + connect kwargs)

ATTEMPTS = int(os.environ.get("AUTODL_ATTEMPTS", "8"))
BACKOFF = float(os.environ.get("AUTODL_BACKOFF", "6"))

# 远端输出是 UTF-8，而 Windows 控制台默认 GBK：不换编码会在打印 ✓ / 中文时直接抛
# UnicodeEncodeError 把整条命令打断（哪怕远端其实跑完了）。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[attr-defined]
    except Exception:                                        # noqa: BLE001
        pass


def connect_hard(attempts: int = ATTEMPTS) -> paramiko.SSHClient:
    autodl_run.load_env_file()
    last: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(
                autodl_run.HOST, port=autodl_run.PORT, username=autodl_run.USER,
                password=autodl_run.PASSWORD, timeout=30, banner_timeout=45,
                auth_timeout=45, allow_agent=False, look_for_keys=False,
            )
            return c
        except paramiko.AuthenticationException as exc:          # retry with RSA-SHA2
            last = exc
            try:
                c = paramiko.SSHClient()
                c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                c.connect(
                    autodl_run.HOST, port=autodl_run.PORT, username=autodl_run.USER,
                    password=autodl_run.PASSWORD, timeout=30, banner_timeout=45,
                    auth_timeout=45, allow_agent=False, look_for_keys=False,
                    disabled_algorithms={"pubkeys": ["rsa-sha2-512", "rsa-sha2-256"]},
                )
                return c
            except Exception as exc2:                            # noqa: BLE001
                last = exc2
        except (paramiko.SSHException, EOFError, OSError, socket.error) as exc:
            last = exc
        print(f"[sshd] attempt {i}/{attempts} failed: {type(last).__name__}: "
              f"{str(last)[:120]}", file=sys.stderr, flush=True)
        if i < attempts:
            time.sleep(BACKOFF * min(i, 3))
    raise SystemExit(f"could not connect after {attempts} attempts: {last}")


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2

    timeout = None
    if args[0] == "--timeout":
        timeout = int(args[1])
        args = args[2:]

    c = connect_hard()
    try:
        if args[0] == "--put":
            sftp = c.open_sftp()
            sftp.put(args[1], args[2])
            sftp.close()
            print("uploaded", args[1], "->", args[2])
            return 0
        if args[0] == "--get":
            sftp = c.open_sftp()
            sftp.get(args[1], args[2])
            sftp.close()
            print("downloaded", args[1], "->", args[2])
            return 0

        if args[0] in ("--file", "--script"):
            src = pathlib.Path(args[1]).read_text(encoding="utf-8")
            remote = "/tmp/_retry_cmd_%d.sh" % os.getpid()
            sftp = c.open_sftp()
            with sftp.file(remote, "w") as fh:
                fh.write(src)
            sftp.close()
            cmd = "bash %s" % remote
        else:
            cmd = args[0]

        _stdin, stdout, stderr = c.exec_command(cmd, timeout=timeout, get_pty=False)
        # stream, so a long download still shows progress before it ends
        chan = stdout.channel
        chan.settimeout(1.0)
        buf_out, buf_err = b"", b""
        while True:
            if chan.recv_ready():
                data = chan.recv(65536)
                buf_out += data
                sys.stdout.write(data.decode("utf-8", "replace"))
                sys.stdout.flush()
            if chan.recv_stderr_ready():
                buf_err += chan.recv_stderr(65536)
                sys.stderr.write(buf_err.decode("utf-8", "replace")[-4096:])
                sys.stderr.flush()
                buf_err = b""
            if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
                break
            time.sleep(0.05)
        rc = chan.recv_exit_status()
        print(f"\n[remote exit code: {rc}]")
        return rc
    finally:
        c.close()


if __name__ == "__main__":
    sys.exit(main())
