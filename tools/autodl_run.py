#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Run shell commands on the AutoDL instance over SSH (paramiko).

Usage:
  python tools/autodl_run.py "nvidia-smi"                 # single command
  python tools/autodl_run.py --file cmds.sh               # run a local script remotely
  python tools/autodl_run.py --put local remote           # upload a file
  python tools/autodl_run.py --get remote local           # download a file/post

Secrets come from env vars or the local (git-ignored) file tools/autodl.env.
"""
import os
import sys
import pathlib

import paramiko

HOST = os.environ.get("AUTODL_HOST", "connect.west?.seetacloud.com")
PORT = int(os.environ.get("AUTODL_PORT", "12345"))
USER = os.environ.get("AUTODL_USER", "root")
PASSWORD = os.environ.get("AUTODL_PASS", "")
ENVF = pathlib.Path(__file__).with_name("autodl.env")


def load_env_file(path=None):
    """读实例连接信息。

    优先级：环境变量 AUTODL_* > 指定文件 > 默认文件。
    **环境变量优先**很重要：以前是文件无条件覆盖环境变量，换实例时必须改文件，
    而 clone 出来的新机往往只想临时指一下（见 tools/autodl_new.env）。
    用 --env FILE 可以指定另一个实例文件。
    """
    global HOST, PORT, USER, PASSWORD
    envf = pathlib.Path(path) if path else ENVF
    if not envf.exists():
        return
    for raw in envf.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k == "AUTODL_HOST" and not os.environ.get("AUTODL_HOST"):
            HOST = v
        elif k == "AUTODL_PORT" and not os.environ.get("AUTODL_PORT"):
            PORT = int(v)
        elif k == "AUTODL_USER" and not os.environ.get("AUTODL_USER"):
            USER = v
        elif k == "AUTODL_PASS" and not os.environ.get("AUTODL_PASS"):
            PASSWORD = v


def connect(timeout=30):
    last = None
    for kwargs in ({}, {"disabled_algorithms": {"pubkeys": ["rsa-sha2-512", "rsa-sha2-256"]}}):
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(
                HOST, port=PORT, username=USER, password=PASSWORD,
                timeout=timeout, banner_timeout=30, auth_timeout=30,
                allow_agent=False, look_for_keys=False, **kwargs
            )
            return c
        except paramiko.AuthenticationException as exc:
            last = exc
            continue
    raise last


def run(c, cmd, timeout=None):
    stdin, stdout, stderr = c.exec_command(cmd, timeout=timeout, get_pty=False)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out, err


def main():
    args = sys.argv[1:]
    if args and args[0] == "--env":            # 指定实例文件（换机时用）
        load_env_file(args[1])
        args = args[2:]
    else:
        load_env_file()
    if not args:
        print(__doc__)
        return 2

    as_script = args[0] in ("--file", "--script")
    if as_script:
        cmd = pathlib.Path(args[1]).read_text(encoding="utf-8")
    else:
        cmd = args[0]

    c = connect()
    try:
        if as_script:
            # upload to a temp file and bash it: avoids every layer of shell quoting
            remote = "/tmp/_autodl_cmd_%d.sh" % os.getpid()
            sftp = c.open_sftp()
            with sftp.file(remote, "w") as fh:
                fh.write(cmd)
            sftp.close()
            cmd = "bash %s" % remote
        if args[0] == "--put":
            sftp = c.open_sftp()
            sftp.put(args[1], args[2])
            print("uploaded", args[1], "->", args[2])
            return 0
        if args[0] == "--get":
            sftp = c.open_sftp()
            sftp.get(args[1], args[2])
            print("downloaded", args[1], "->", args[2])
            return 0
        timeout = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
        rc, out, err = run(c, cmd, timeout=timeout)
        sys.stdout.write(out)
        if err:
            sys.stderr.write(err)
        print("\n[remote exit code: %d]" % rc)
        return rc
    finally:
        c.close()


if __name__ == "__main__":
    sys.exit(main())
