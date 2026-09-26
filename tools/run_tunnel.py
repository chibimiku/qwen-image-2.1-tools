# -*- coding: utf-8 -*-
"""Run one of the test scripts through an SSH port-forward to the AutoDL service.

    python tools/run_tunnel.py matrix_test.py [--port 16008]
    python tools/run_tunnel.py qwen_chain.py

The target script sees a global BASE pointing at the forwarded local port, so it
can talk to 127.0.0.1:6006 on the remote box without any public URL.
"""
import argparse
import os
import runpy
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import autodl_ssh                                                     # noqa: E402

TOOLS = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("--port", type=int, default=16008)
    ap.add_argument("--remote-port", type=int, default=6006)
    a = ap.parse_args()

    autodl_ssh.load_env()
    c = autodl_ssh.connect()
    fwd = autodl_ssh.ForwardServer(("127.0.0.1", a.port), autodl_ssh.Handler)
    fwd.dst_host, fwd.dst_port = "127.0.0.1", a.remote_port
    fwd.transport = c.get_transport()
    threading.Thread(target=fwd.serve_forever, daemon=True).start()
    print(f"[fwd] 127.0.0.1:{a.port} -> remote 127.0.0.1:{a.remote_port} over ssh", flush=True)

    path = a.script if os.path.isabs(a.script) else os.path.join(TOOLS, a.script)
    ns = {"__name__": "__main__", "__file__": path,
          "BASE": f"http://127.0.0.1:{a.port}"}
    try:
        runpy.run_path(path, init_globals=ns, run_name="__main__")
    finally:
        fwd.shutdown()
        c.close()
        print("[fwd] closed", flush=True)


if __name__ == "__main__":
    main()
