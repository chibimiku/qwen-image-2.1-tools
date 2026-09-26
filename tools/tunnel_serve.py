#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把远端服务的端口映射到本机（SSH 本地转发），关掉窗口即断开。

只用 paramiko，不依赖系统 ssh.exe —— Windows 自带 OpenSSH 9.5 与部分 8.x 服务端
存在公钥签名兼容问题（服务器接受密钥但验签失败），走密码通道最稳。

    python tunnel_serve.py                      # 读同目录的 tunnel.conf
    python tunnel_serve.py --host H --port P --user root --password PW
    python tunnel_serve.py --local-port 16006 --remote-port 6006
"""
import argparse
import os
import select
import socketserver
import sys
import threading
import time

try:
    import paramiko
except ImportError:
    print("缺少 paramiko： pip install paramiko")
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(HERE, "tunnel.conf")


def load_conf():
    cfg = {}
    if os.path.exists(CONF):
        for raw in open(CONF, encoding="utf-8"):
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            chan = self.server.transport.open_channel(
                "direct-tcpip", (self.server.dst_host, self.server.dst_port),
                self.request.getpeername())
        except Exception as exc:                                      # noqa: BLE001
            print(f"[tunnel] 打开通道失败: {exc}", flush=True)
            return
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
        except Exception:                                             # noqa: BLE001
            pass
        finally:
            chan.close()
            try:
                self.request.close()
            except Exception:                                         # noqa: BLE001
                pass


class ForwardServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    conf = load_conf()
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=conf.get("host"))
    ap.add_argument("--port", type=int, default=int(conf.get("port", 22)))
    ap.add_argument("--user", default=conf.get("user", "root"))
    ap.add_argument("--password", default=conf.get("password"))
    ap.add_argument("--key", default=conf.get("key"))
    ap.add_argument("--local-port", type=int, default=int(conf.get("local_port", 16006)))
    ap.add_argument("--remote-port", type=int, default=int(conf.get("remote_port", 6006)))
    ap.add_argument("--remote-host", default=conf.get("remote_host", "127.0.0.1"))
    a = ap.parse_args()

    if not a.host:
        print("缺少目标主机：用 --host 或写进 tunnel.conf")
        return 2

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs = dict(port=a.port, username=a.user, timeout=20, banner_timeout=30,
                  auth_timeout=30, allow_agent=False, look_for_keys=False)
    if a.key and os.path.exists(a.key):
        kwargs["key_filename"] = a.key
    else:
        kwargs["password"] = a.password
    try:
        client.connect(a.host, **kwargs)
    except Exception as exc:                                          # noqa: BLE001
        print(f"[tunnel] 连接失败: {type(exc).__name__}: {exc}")
        return 1

    transport = client.get_transport()
    transport.set_keepalive(30)

    srv = ForwardServer(("127.0.0.1", a.local_port), Handler)
    srv.dst_host, srv.dst_port = a.remote_host, a.remote_port
    srv.transport = transport
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    print(f"[tunnel] 已建立： http://127.0.0.1:{a.local_port}/  ->  "
          f"{a.host}:{a.port}  ->  {a.remote_host}:{a.remote_port}")
    print("[tunnel] 关闭本窗口（或 Ctrl+C）即断开", flush=True)

    try:
        while transport.is_active():
            time.sleep(2)
        print("[tunnel] SSH 连接已断开")
    except KeyboardInterrupt:
        print("\n[tunnel] 手动中断")
    finally:
        srv.shutdown()
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
