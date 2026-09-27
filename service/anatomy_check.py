#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Low-resource, opt-in human-anatomy review for generated images.

The checker is deliberately fail-open: a missing model, malformed response, or
low-confidence verdict never burns another expensive diffusion run.  The model
is loaded lazily on the CPU only when a request enables anatomy checking.

实测记录（2026-09-26，Xeon 8470Q / 208 核，bf16 + AMX）:

* **SmolVLM-500M-Instruct 不能用**：它按 `PASS|置信度|理由` 的格式回答不出来，
  永远只回一句 `PASS.` —— 解析全部落到 fail-open，自动重跑等于不存在。
* **SmolVLM2-2.2B-Instruct 会按格式回答**（`PASS|0.99|...`），单张 CPU 判图
  16~40s、常驻 ~5.6 GB 内存、完全不占显存。
* 但要清醒：它对明显缺陷**仍然偏保守**。用一张"一个身体两个头"的对照图实测，
  2.2B 能描述出 "A person with two faces"、被问几个头也答 2，可是问 PASS/FAIL
  时照样回 `PASS`。所以这道闸门是"能挡住就挡"，不是"一定能挡住" —— 这也是
  fail-open + 高置信度阈值设计的原因。要更准，得换成更大的 VLM 或改成
  "数头/数肢 vs 人数"这类可核对的问法（见 docs/CHANGELOG.md）。
"""
from __future__ import annotations

import os
import re
import threading
import time
from typing import Any, Dict

import torch
from PIL import Image


MODEL_ID = os.environ.get("QWEN_ANATOMY_MODEL", "HuggingFaceTB/SmolVLM2-2.2B-Instruct")
DEVICE = os.environ.get("QWEN_ANATOMY_DEVICE", "cpu").lower()
# auto: GPU→float16，CPU→bfloat16（本机 Xeon 8470Q 有 AMX/avx512_bf16，
# 实测同一张图 38.4s → 20.3s，快约 1.8 倍；没有硬件 bf16 的机器请显式设 float32）
DTYPE_REQ = os.environ.get("QWEN_ANATOMY_DTYPE", "auto").lower()
MIN_CONFIDENCE = float(os.environ.get("QWEN_ANATOMY_MIN_CONFIDENCE", "0.78"))
MAX_EDGE = int(os.environ.get("QWEN_ANATOMY_MAX_EDGE", "768"))
MAX_NEW_TOKENS = int(os.environ.get("QWEN_ANATOMY_MAX_NEW_TOKENS", "72"))


def _pick_dtype():
    if DTYPE_REQ in ("float32", "fp32"):
        return torch.float32
    if DTYPE_REQ in ("bfloat16", "bf16"):
        return torch.bfloat16
    if DTYPE_REQ in ("float16", "fp16", "half"):
        return torch.float16
    return torch.float16 if DEVICE.startswith("cuda") else torch.bfloat16   # auto


def is_local_dir(path: str) -> bool:
    """模型路径是不是本地目录（而不是 HF repo id）。"""
    return os.path.isdir(path)


# 本地目录 → 直接离线。放在**模块导入期**，而不是等 _load()：
# huggingface_hub 在 import 时会读一次 HF_HUB_OFFLINE 缓存到自己的常量里，
# 之后再改 os.environ 可能不生效。实测踩过：调用方已经 export 了
# HF_HUB_OFFLINE=1，加载仍去连 huggingface.co —— 因为那是在导入之后设的。
if is_local_dir(MODEL_ID):
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


def ensure_offline_if_local(model_ref: str) -> bool:
    """模型已经是本地目录时，强制 HF 走离线模式。返回是否生效。

    为什么必须做：就算目录里文件齐全，`from_pretrained` 默认仍会为每个文件向
    huggingface.co 发一次 HEAD（查有没有新版本）。集群内网机器出不了外网，
    于是加载被拖进 5 次重试 + 指数退避，最后抛 OSError。
    而 inspect_image 是 **fail-open** 的：加载失败会返回 passed=True ——
    调用方看到的是"模型说全部没问题、置信度 0.00"，很容易误读成"没有异常"。
    """
    if not is_local_dir(model_ref):
        return False
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    return os.environ.get("HF_HUB_OFFLINE") == "1"


_model = None
_processor = None
_load_error = None
_dtype_used = None
_lock = threading.Lock()

_INSTRUCTION = """You are a conservative generated-image quality inspector.
Inspect ONLY clearly visible human anatomy. FAIL only for an obvious severe defect such as an extra,
missing, fused or disconnected limb; duplicated head or torso; severely malformed visible hand or face;
or impossible body geometry. PASS if there is no person, the body part is cropped/occluded, the image is
stylized, or you are uncertain. Do not judge beauty, clothing, text, identity, or prompt compliance.
Reply with exactly one line: PASS|confidence from 0 to 1|short reason
or: FAIL|confidence from 0 to 1|short reason"""


def _load() -> None:
    global _model, _processor, _load_error, _dtype_used
    if _model is not None or _load_error is not None:
        return
    with _lock:
        if _model is not None or _load_error is not None:
            return
        try:
            from transformers import AutoProcessor
            try:
                from transformers import AutoModelForImageTextToText as ModelClass
            except ImportError:
                from transformers import AutoModelForVision2Seq as ModelClass

            # 本地目录就直接离线读，别让每个文件都去 HEAD huggingface.co
            ensure_offline_if_local(MODEL_ID)
            _processor = AutoProcessor.from_pretrained(MODEL_ID)
            dtype = _pick_dtype()
            _model = ModelClass.from_pretrained(
                MODEL_ID, dtype=dtype, low_cpu_mem_usage=True,
            ).to(DEVICE)
            _model.eval()
            _dtype_used = str(dtype).replace("torch.", "")
        except Exception as exc:  # fail-open is intentional
            _load_error = f"{type(exc).__name__}: {exc}"


def status() -> Dict[str, Any]:
    return {
        "model": MODEL_ID,
        "device": DEVICE,
        # 还没加载时也报出"将要用的精度"，否则前端看到 null 不知道会走哪条路
        "dtype": _dtype_used or str(_pick_dtype()).replace("torch.", ""),
        "loaded": _model is not None,
        "load_error": _load_error,
        "min_confidence": MIN_CONFIDENCE,
        "max_edge": MAX_EDGE,
    }


def inspect_image(image: Image.Image, original_prompt: str = "") -> Dict[str, Any]:
    """Return a structured verdict. ``passed`` is always true on uncertainty/error."""
    started = time.time()
    _load()
    if _model is None or _processor is None:
        return {
            "passed": True, "label": "unavailable", "confidence": 0.0,
            "reason": _load_error or "checker unavailable", "fail_open": True,
            "elapsed_s": round(time.time() - started, 2),
        }

    try:
        sample = image.convert("RGB")
        sample.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
        text = _INSTRUCTION
        if original_prompt:
            text += "\nOriginal request (context only): " + original_prompt[:500]
        messages = [{"role": "user", "content": [
            {"type": "image"}, {"type": "text", "text": text},
        ]}]
        prompt = _processor.apply_chat_template(messages, add_generation_prompt=True)
        inputs = _processor(text=prompt, images=[sample], return_tensors="pt")
        inputs = {k: v.to(DEVICE) if hasattr(v, "to") else v for k, v in inputs.items()}
        input_len = inputs["input_ids"].shape[1]
        with torch.inference_mode():
            ids = _model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False)
        answer = _processor.batch_decode(ids[:, input_len:], skip_special_tokens=True)[0].strip()
        match = re.search(r"\b(PASS|FAIL)\s*\|\s*(0(?:\.\d+)?|1(?:\.0+)?)\s*\|\s*(.+)",
                          answer, flags=re.I | re.S)
        if not match:
            return {
                "passed": True, "label": "uncertain", "confidence": 0.0,
                "reason": "checker returned an unparseable verdict", "fail_open": True,
                "elapsed_s": round(time.time() - started, 2),
            }
        label = match.group(1).lower()
        confidence = float(match.group(2))
        high_confidence_failure = label == "fail" and confidence >= MIN_CONFIDENCE
        return {
            "passed": not high_confidence_failure,
            "label": label,
            "confidence": confidence,
            "reason": " ".join(match.group(3).strip().split())[:240],
            "fail_open": label == "fail" and not high_confidence_failure,
            "elapsed_s": round(time.time() - started, 2),
        }
    except Exception as exc:  # inference errors must not discard a usable image
        return {
            "passed": True, "label": "error", "confidence": 0.0,
            "reason": f"{type(exc).__name__}: {exc}"[:240], "fail_open": True,
            "elapsed_s": round(time.time() - started, 2),
        }
