# -*- coding: utf-8 -*-
# 表情专项要在隧道下跑：先起 tunnel helper，再让 qwen_report.py 在进程内使用 BASE
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import autodl_ssh            # noqa: E402
import qwen_report           # noqa: E402


def main():
    autodl_ssh.load_env()
    c = autodl_ssh.connect()
    fwd = autodl_ssh.ForwardServer(("127.0.0.1", 16007), autodl_ssh.Handler)
    fwd.dst_host, fwd.dst_port = "127.0.0.1", 6006
    fwd.transport = c.get_transport()
    import threading
    threading.Thread(target=fwd.serve_forever, daemon=True).start()
    print("[fwd] 127.0.0.1:16007 -> remote 6006")
    qwen_report.BASE = "http://127.0.0.1:16007"
    sys.argv = ["qwen_report.py", "--run"]
    try:
        qwen_report.main()
    finally:
        fwd.shutdown()
        c.close()
        print("[fwd] closed")


if __name__ == "__main__":
    main()
