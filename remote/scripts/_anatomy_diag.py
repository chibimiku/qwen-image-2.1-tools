#!/usr/bin/env python3
"""审图模型到底为什么加载不起来 —— 打印完整异常与本地目录检查。

`inspect_image` 是 fail-open 的（加载不了就返回 PASS），所以加载失败在
调用方看来只是"全 0% FAIL"，很容易被当成"模型说没问题"。这里把真错误挖出来。
"""
import os
import sys
import traceback

MODEL = os.environ.get("QWEN_ANATOMY_MODEL", "/root/autodl-tmp/models/SmolVLM2-2.2B-Instruct")
print("MODEL      =", MODEL)
print("isdir      =", os.path.isdir(MODEL))
print("HF_HUB_OFFLINE       =", os.environ.get("HF_HUB_OFFLINE"))
print("TRANSFORMERS_OFFLINE =", os.environ.get("TRANSFORMERS_OFFLINE"))
print("HF_HOME    =", os.environ.get("HF_HOME"))
print("HOME       =", os.environ.get("HOME"))
print("cwd        =", os.getcwd())
if os.path.isdir(MODEL):
    print("files      =", sorted(os.listdir(MODEL)))
    # HF 缓存目录长什么样：本地目录若被当成 repo id，会去 cache 里找一个
    # models--XXX--YYY 的文件夹
    cache = os.path.join(os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface")), "hub")
    print("hub cache  =", cache, "exists:", os.path.isdir(cache))
    if os.path.isdir(cache):
        print("  entries  =", sorted(os.listdir(cache))[:20])

print("\n--- import transformers ---")
try:
    import transformers
    print("transformers", transformers.__version__)
    import huggingface_hub
    print("huggingface_hub", huggingface_hub.__version__)
except Exception:
    traceback.print_exc()
    sys.exit(1)

print("\n--- AutoProcessor.from_pretrained(local dir) ---")
from transformers import AutoProcessor
try:
    p = AutoProcessor.from_pretrained(MODEL)
    print("OK:", type(p).__name__)
except Exception:
    print("FAILED:")
    traceback.print_exc()
    sys.exit(2)

print("\n--- AutoModelForImageTextToText.from_pretrained(local dir) ---")
try:
    from transformers import AutoModelForImageTextToText as ModelClass
except ImportError:
    from transformers import AutoModelForVision2Seq as ModelClass
try:
    m = ModelClass.from_pretrained(MODEL, dtype="bfloat16", low_cpu_mem_usage=True)
    print("OK:", type(m).__name__, sum(p.numel() for p in m.parameters()) / 1e9, "B params")
except Exception:
    print("FAILED:")
    traceback.print_exc()
    sys.exit(3)
print("\nALL OK")
