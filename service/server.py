#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Qwen-Image-2.1 HTTP service (AutoDL).

Wraps diffusers' QwenImage21Pipeline behind an OpenAI-ish /v1 API so other
drawing services can call it over plain HTTP.

Env:
  QWEN_MODEL_DIR   local checkpoint dir            (default /root/autodl-tmp/Qwen-Image-2.1)
  QWEN_PORT        listen port                     (default 6006)
  QWEN_MOCK        1 = never touch the GPU, return placeholder PNGs
  QWEN_FORCE_CPU   1 = load on CPU (debug only)
  QWEN_OFFLOAD     cpu|model|sequential|none       (default none)
  QWEN_TILE_VAE    1 = tiled VAE decode (saves VRAM, slower)
  QWEN_TORCH_DTYPE bfloat16|float16                (default bfloat16)
  QWEN_API_KEY     primary API key (see also QWEN_API_KEYS)
  QWEN_API_KEYS    extra keys, comma separated — all of them work
  QWEN_UI_KEY      inject|auto|off                 (default auto)
  QWEN_SESSION_HOURS   session cookie TTL hours    (default 24)
  QWEN_MAX_QUEUE   max queued jobs                 (default 64)
"""
import asyncio
import base64
import inspect
import io
import os
import random
import re
import secrets
import time
import uuid
from urllib.parse import quote
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import torch
import uvicorn
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse, Response
from PIL import Image

MODEL_DIR = os.environ.get("QWEN_MODEL_DIR", "/root/autodl-tmp/Qwen-Image-2.1")
PORT = int(os.environ.get("QWEN_PORT", "6006"))
# WebUI：优先取 QWEN_UI_DIR，其次取本文件旁边的 ui/ 目录
_HERE = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.environ.get("QWEN_UI_DIR", os.path.join(_HERE, "ui"))
MOCK = os.environ.get("QWEN_MOCK", "0") == "1"
FORCE_CPU = os.environ.get("QWEN_FORCE_CPU", "0") == "1"
# mode: auto  -> mock when no GPU is attached (no-卡 mode), real inference when a GPU shows up
#       real  -> always require a GPU, return 409 "no GPU" instead of a placeholder image
#       mock  -> never touch the GPU
MODE = os.environ.get("QWEN_MODE", "auto").lower()
OFFLOAD = os.environ.get("QWEN_OFFLOAD", "none").lower()
TILE_VAE = os.environ.get("QWEN_TILE_VAE", "0") == "1"
DTYPE_NAME = os.environ.get("QWEN_TORCH_DTYPE", "bfloat16")
API_KEY = os.environ.get("QWEN_API_KEY", "")            # 主 key（会在控制台提示里显示为"当前 key"）
# 允许多个 key 同时有效（逗号分隔），例如：新随机串,1730
# 用途：换 key 时给旧 key 一个过渡期；或者给自己人一个短口令、对外用长随机串
EXTRA_KEYS = os.environ.get("QWEN_API_KEYS", "")
# 控制台页面怎么处理 key —— 分享镜像给别人时务必设成 auto/off
#   inject : 把 key 渲染进页面并自动填好（只有自己用才这么设；等价于打开页面即拿到 key）
#   auto   : 不注入，浏览器自己填（首次询问一次，存 localStorage）—— 分享场景用这个
#   off    : 页面按"服务无鉴权"工作（要求 QWEN_API_KEY 也为空）
UI_KEY_MODE = os.environ.get("QWEN_UI_KEY", "inject").lower()
# ── 会话（浏览器登录后拿到的 HttpOnly Cookie）────────────────────────────────
# 有了它，浏览器端就**不需要把 key 存进 JS**（localStorage / 变量都不必），
# 页面里的 JS 从头到尾看不到 API Key，Cookie 也不会被 XSS 读走。
SESSION_COOKIE = "qwensess"
SESSION_TTL = int(os.environ.get("QWEN_SESSION_HOURS", "24")) * 3600
SESSIONS: Dict[str, float] = {}          # token -> 过期时间戳
COOKIE_SECURE = os.environ.get("QWEN_COOKIE_SECURE", "1") == "1"   # 公网是 https，默认 Secure
MAX_QUEUE = int(os.environ.get("QWEN_MAX_QUEUE", "64"))
OUT_DIR = os.environ.get("QWEN_OUT_DIR", os.path.join(os.path.dirname(MODEL_DIR.rstrip("/")), "outputs"))
MODEL_VERSION = "Qwen-Image-2.1"
# 48G 单卡（魔改 4090）全 BF16 常驻经验值：权重 32.4 GiB + 每张 2048² latent 约 8 GiB + 余量
SAFETY_GIB = float(os.environ.get("QWEN_SAFETY_GIB", "2.0"))
PRELOAD = os.environ.get("QWEN_PRELOAD", "1") == "1"
LATENT_GIB_2K = float(os.environ.get("QWEN_LATENT_GIB_2K", "8.0"))
# 二次项系数（G/MP²）：分模式校准，见 estimate_transient_gib 的说明
LATENT_QUADRATIC_EDIT = float(os.environ.get("QWEN_LATENT_QUADRATIC_EDIT", "3.65"))
LATENT_QUADRATIC_T2I = float(os.environ.get("QWEN_LATENT_QUADRATIC_T2I", "0.5"))

ASPECT_RATIOS = {
    "1:1": (2048, 2048), "4:3": (2400, 1792), "3:4": (1792, 2400),
    "3:2": (2528, 1696), "2:3": (1696, 2528), "16:9": (2752, 1536), "9:16": (1536, 2752),
}

_pipe = None
_pipe_lock = asyncio.Lock()
_gpu_lock = asyncio.Lock()          # one generation at a time (single GPU)
_jobs: Dict[str, Dict[str, Any]] = {}
_load_error: Optional[str] = None
_peak_gib = 0.0
_queue_depth = 0


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Preload the pipeline: on a 48G card the weights fit, so first-request
    latency should not include a multi-minute load."""
    global _load_error
    if PRELOAD and not _effective_mock():
        try:
            await get_pipe()
        except Exception as exc:                                # noqa: BLE001
            _load_error = f"{type(exc).__name__}: {exc}"
            print("[startup] preload failed:", _load_error, flush=True)
    yield
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


app = FastAPI(title="Qwen-Image-2.1 API", version="2.1.0", lifespan=_lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)
# 页面挂在本服务上时同源，但脚本/其他端口（含 SSH 隧道里的包装页）来调就需要放开 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)


def _effective_mock() -> bool:
    """True when we should fabricate a placeholder instead of running the model."""
    if MODE == "mock":
        return True
    if MODE == "real":
        return False
    return not torch.cuda.is_available()



def _require_gpu():
    if MODE == "real" and not torch.cuda.is_available():
        raise HTTPException(409, "no GPU attached: this instance is in 无卡模式, power it on with a GPU first")


def estimate_transient_gib(width: int, height: int, steps: int, mode: str = "t2i") -> float:
    """本次运行需要的**额外**显存（不含已常驻的权重）。

    权重已经在显存里，而且 PyTorch 会复用缓存块，所以拿"权重 + 临时量"去比可用显存
    会把权重重复计一遍，导致误报 507。

    **两条路线的曲线不一样，实测校准（48G 卡，权重常驻 30.2G，可用 ≈ 47.4G）**：

      文生图 t2i —— 曲线很平，别用编辑的系数去拦它：
          2048²/40 步 实测峰值 32.5G  -> 临时量 ≈ 2.3G（能跑，绝不能拦）

      编辑 edit —— 陡得多，因为还要编码参考图（条件 latent + 图像 token 一起进序列）：
          1024²/6 步   峰值 ≈ 44.7G（实测）-> 临时量 ≈ 14.5G
          1200×1600（1.92MP）通过 / 1280×1696（2.17MP）OOM
          -> 二次项 3.65 G/MP² 正好在 1.92MP 放行、2.17MP 拦住

    seq = max(线性项, 二次项)，取大值保证不低估。
    """
    mp = width * height / 1e6
    linear = LATENT_GIB_2K * (width * height) / (2048.0 * 2048.0)
    if mode == "edit":
        quad = LATENT_QUADRATIC_EDIT * mp * mp      # 3.65 G/MP²
    else:
        quad = LATENT_QUADRATIC_T2I * mp * mp       # 0.5 G/MP²（2048² -> 2.1G，不误拦）
    step_gib = 0.6 * max(0, steps - 25) / 25.0      # 步数多会多留一点
    return round(max(linear, quad) + step_gib, 2)


def preflight_vram(width: int, height: int, steps: int, mode: str = "t2i"):
    """只在临时量明显塞不下时拦；否则放行，真 OOM 再翻译成可读的 507。"""
    if not torch.cuda.is_available():
        return
    need = estimate_transient_gib(width, height, steps, mode)
    free_gib = torch.cuda.mem_get_info()[0] / 1024 ** 3
    if need > free_gib:
        hint = ("编辑建议 ≤ 1.92MP（如 1200×1600）；要更高只能开 QWEN_OFFLOAD=model"
                if mode == "edit" else "文生图建议 ≤ 2048²（8.4MP）")
        raise HTTPException(507, (
            f"preflight: {width}x{height}/{steps} steps 需要约 {need:.1f} GiB 额外显存，"
            f"当前只有 {free_gib:.1f} GiB 可用。{hint}。"
            f"（临时量估算已按实测校准：编辑 1.92MP 通过 / 2.17MP 失败）"
        ))


def _dtype():
    if DTYPE_NAME in ("float16", "fp16", "half"):
        return torch.float16
    return torch.bfloat16


def _detect_dtype_kwarg() -> bool:
    """Older diffusers wants `torch_dtype`, newer wants `dtype`; detect once."""
    try:
        import inspect as _inspect
        from diffusers import DiffusionPipeline
        sig = _inspect.signature(DiffusionPipeline.from_pretrained)
        return "dtype" in sig.parameters
    except Exception:                                          # noqa: BLE001
        return False


_SUPPORTS_DTYPE = _detect_dtype_kwarg()
DTYPE_KWARG = "dtype" if _SUPPORTS_DTYPE else "torch_dtype"


def gpu_info() -> Dict[str, Any]:
    if MOCK or not torch.cuda.is_available():
        return {"available": False, "mock": MOCK}
    idx = torch.cuda.current_device()
    free, total = torch.cuda.mem_get_info()
    return {
        "available": True,
        "name": torch.cuda.get_device_name(idx),
        "total_gb": round(total / 1024 ** 3, 1),
        "free_gb": round(free / 1024 ** 3, 1),
        "allocated_gb": round(torch.cuda.memory_allocated() / 1024 ** 3, 2),
        "reserved_gb": round(torch.cuda.memory_reserved() / 1024 ** 3, 2),
        "capability": ".".join(map(str, torch.cuda.get_device_capability(idx))),
    }


async def get_pipe():
    """Load the pipeline once, on first use."""
    global _pipe
    if _pipe is not None:
        return _pipe
    async with _pipe_lock:
        if _pipe is not None:
            return _pipe
        if _effective_mock():
            return None
        if not os.path.isdir(MODEL_DIR) or not os.path.exists(os.path.join(MODEL_DIR, "model_index.json")):
            raise HTTPException(503, f"checkpoint not ready at {MODEL_DIR} (download still running?)")
        from diffusers import QwenImage21Pipeline  # noqa: WPS433
        dtype = _dtype()
        kwargs: Dict[str, Any] = {DTYPE_KWARG: dtype}
        if torch.cuda.is_available() and not FORCE_CPU:
            kwargs["device_map"] = None
        pipe = QwenImage21Pipeline.from_pretrained(MODEL_DIR, **kwargs)
        if FORCE_CPU or not torch.cuda.is_available():
            pipe.to("cpu")
        elif OFFLOAD == "model":
            pipe.enable_model_cpu_offload()
        elif OFFLOAD == "sequential":
            pipe.enable_sequential_cpu_offload()
        elif OFFLOAD == "cpu":
            pipe.enable_model_cpu_offload()
        else:
            pipe.to("cuda")
        if TILE_VAE:
            pipe.vae.enable_tiling()
        try:
            pipe.set_progress_bar_config(disable=True)
        except Exception:
            pass
        _pipe = pipe
        return _pipe


def mock_png(width: int, height: int, text: str) -> bytes:
    from PIL import ImageDraw
    img = Image.new("RGBA", (min(width, 1024), min(height, 1024)), (24, 26, 34, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, img.width - 1, img.height - 1], outline=(90, 180, 255, 255), width=4)
    d.text((24, 24), "MOCK MODE\nno GPU attached\n" + text[:80], fill=(240, 240, 240, 255))
    buf = io.BytesIO()
    img.convert("RGBA").save(buf, format="PNG")
    return buf.getvalue()


def _resolve_size(width, height, size, aspect_ratio):
    if aspect_ratio and aspect_ratio in ASPECT_RATIOS:
        return ASPECT_RATIOS[aspect_ratio]
    if size:
        try:
            w, h = str(size).lower().split("x")
            return int(w), int(h)
        except Exception:
            raise HTTPException(400, f"bad size '{size}', expected 'WxH'")
    return int(width or 2048), int(height or 2048)


def _b64(png: bytes) -> str:
    return base64.b64encode(png).decode("ascii")


# --------------------------------------------------------------------------- #
# 进度跟踪（真实步数，来自管线的 per-step 回调）
# --------------------------------------------------------------------------- #
_progress: Dict[str, Dict[str, Any]] = {}
_MAX_PROGRESS = 40


def _new_progress(rid: Optional[str], total_steps: int) -> Dict[str, Any]:
    rid = rid or ("req_" + uuid.uuid4().hex[:12])
    p = {
        "request_id": rid, "status": "queued", "phase": "queued", "step": 0, "steps_done": 0,
        "total": int(max(1, total_steps)), "pct": 0.0,
        "elapsed_s": 0.0, "eta_s": None, "per_step_s": None,
        "durations": [], "started": time.time(), "last_step_at": time.time(),
        "finished_at": None, "callback_unavailable": False, "error": None,
        "decode_started": None, "decode_s": None, "encode_s": None,
    }
    _progress[rid] = p
    if len(_progress) > _MAX_PROGRESS:
        for k in sorted(_progress, key=lambda k: _progress[k]["started"])[:-_MAX_PROGRESS]:
            _progress.pop(k, None)
    return p


def _progress_view(p: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """对外的进度视图（不含内部计时字段）；未开始的行进过程用“按需推算”补 ETA。"""
    if p is None:
        return None
    if p["status"] in ("queued", "running") and p["elapsed_s"]:
        p["elapsed_s"] = round(time.time() - p["started"], 2)
        if p["steps_done"] and not p["eta_s"]:
            left = max(0, p["total"] - p["steps_done"])
            p["eta_s"] = round(left * (p["elapsed_s"] / p["steps_done"]), 1)
    # 最后一步的回调已经跑完，但图还没回来 → 主动声明进入收尾阶段。
    # 纯粹看 status 会漏掉这个窗口（它短到轮询经常抓不到），所以用回调里的
    # steps_done 来判断：这样前端一定能看到一句"在收尾"，而不是干巴巴的 100%。
    if p["status"] == "running" and p["total"] and p["steps_done"] >= p["total"]:
        p["status"] = "decoding"
        p["phase"] = "decoding"
        p["pct"] = 99.0
    keys = ("request_id", "status", "phase", "step", "steps_done", "total", "pct", "elapsed_s",
            "eta_s", "per_step_s", "callback_unavailable", "error")
    view = {k: p.get(k) for k in keys}
    d = p.get("durations") or []
    if d:
        view["last_step_s"] = d[-1]
        view["min_step_s"] = min(d)
        view["max_step_s"] = max(d)
    view["queue_depth"] = _queue_depth
    return view


async def _generate(req: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Blocking-ish generation, one request at a time on the GPU."""
    global _queue_depth
    prompt = req["prompt"]
    width, height = req["width"], req["height"]
    steps = req["num_inference_steps"]
    seed = req.get("seed")
    fmt = req.get("output_format", "png").lower()
    transparent = bool(req.get("transparent"))
    images_in: List[Image.Image] = req.get("images") or []

    if transparent and "RGBA image with transparency" not in prompt:
        prompt = ("This is an RGBA image with transparency. " + prompt +
                  " The image has alpha channel and the background is transparent.")

    async with _gpu_lock:
        _queue_depth = max(0, _queue_depth - 1)
        t0 = time.time()
        _require_gpu()
        # the allocator keeps freed blocks instead of returning them to the driver;
        # release them so the preflight sees the real headroom (weights stay resident)
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        preflight_vram(width, height, steps, "edit" if images_in else "t2i")
        pipe = await get_pipe()
        if pipe is None:
            png = mock_png(width, height, prompt)
            out = [{"b64_json": _b64(png), "seed": seed if seed is not None else 0,
                    "width": width, "height": height}]
            return out
        # 生成前的准备开销（显存回收 / 权重已是常驻）要单独计时，
        # 否则用户看到的"每步耗时"会被这段一次性开销污染
        prep_s = round(time.time() - t0, 2)
        # ── 种子 ──
        # 以前这里留空就传 generator=None，管线走全局 RNG —— 图是随机的没错，
        # 但返回里写 seed: 0，而 seed=0 跟"不传 seed"并不等价，拿 0 复现不出同一张。
        # 现在改成：不给就自己掷一个真随机种子，用它做 generator，然后如实返回。
        # 于是"随机生成"和"记下种子可复现"能同时成立。
        seed_given = seed is not None
        if not seed_given:
            seed = random.randrange(0, 2 ** 31 - 1)
        generator = torch.Generator("cuda" if torch.cuda.is_available() else "cpu").manual_seed(int(seed))
        kwargs: Dict[str, Any] = {
            "prompt": prompt,
            "num_inference_steps": steps,
            "width": width,
            "height": height,
            "generator": generator,
        }
        # ── 尺寸：管线规则（读 diffusers 源码 + 实测）
        #   output_resolution 决定"像素预算"（预算 = 分辨率的平方），
        #   比例来自参考图；显式给 width/height 则直接用你给的值。
        #   所以：编辑时没显式给宽高 → 丢掉 width/height，让管线按
        #   output_resolution + 参考图比例自己算；给了 → 传下去（可出 2K）。
        if images_in:
            kwargs["image"] = images_in[0] if len(images_in) == 1 else images_in
            keep = bool(req.get("explicit_size"))
            if not keep:
                kwargs.pop("width", None)
                kwargs.pop("height", None)
        if req.get("guidance_scale") is not None:
            # 管线**没有** guidance_scale 这个参数（只有 true_cfg_scale），
            # 以前直接往 kwargs 里塞会 TypeError 500。这里做映射，两个名字都收。
            kwargs["true_cfg_scale"] = float(req["guidance_scale"])
        if req.get("negative_prompt"):
            kwargs["negative_prompt"] = req["negative_prompt"]
        if req.get("output_resolution"):
            # 决定去噪分辨率与实际输出边长（默认 1024），比 width/height 更管用
            kwargs["output_resolution"] = int(req["output_resolution"])

        # ---- 真实进度：挂在管线的 per-step 回调上 ----
        prog = _new_progress(req.get("request_id"), steps)
        req["_progress"] = prog
        tot = max(1, int(steps) * max(1, int(getattr(pipe, "num_images_per_prompt", 1) or 1)))

        def _on_step(pipe_ref=None, step=None, timestep=None, callback_kwargs=None, **_ignored):
            """diffusers 每步都会调；用它算真实步数、每步耗时与 ETA。"""
            try:
                idx = int(step if step is not None else callback_kwargs.get("step", 0))
            except Exception:                                    # noqa: BLE001
                idx = prog["step"] + 1
            if idx <= 0:
                idx = prog["step"] + 1
            per = prog["started"] if prog["steps_done"] == 0 else prog["last_step_at"]
            dt = max(1e-6, time.time() - per)
            prog["durations"].append(round(dt, 3))
            if len(prog["durations"]) > 200:
                prog["durations"] = prog["durations"][-200:]
            prog["steps_done"] = min(idx, tot)
            prog["step"] = prog["steps_done"]
            prog["total"] = tot
            prog["last_step_at"] = time.time()
            prog["per_step_s"] = round(sum(prog["durations"]) / len(prog["durations"]), 3)
            prog["elapsed_s"] = round(time.time() - prog["started"], 2)
            left = max(0, tot - prog["steps_done"])
            prog["eta_s"] = round(left * prog["per_step_s"], 1)
            prog["pct"] = round(100.0 * prog["steps_done"] / tot, 1)
            return callback_kwargs or {}

        try:
            _probe = inspect.signature(pipe.__call__).parameters
            _takes_cb = ("callback_on_step_end" in _probe
                         or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in _probe.values()))
            # 只把管线真正接受的参数传下去。参数名对不上（比如有人按通用叫法写 guidance_scale）
            # 以前会一路走到模型内部才炸成 TypeError 500；现在在门口拦掉并记日志。
            if not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in _probe.values()):
                _dropped = [k for k in kwargs if k not in _probe]
                for k in _dropped:
                    kwargs.pop(k, None)
                if _dropped:
                    print(f"[warn] pipeline 不认识这些参数，已丢弃：{_dropped}", flush=True)
        except Exception:                                        # noqa: BLE001
            _takes_cb = True
        if _takes_cb:
            kwargs["callback_on_step_end"] = _on_step
            kwargs["callback_on_step_end_tensor_inputs"] = []

        def _call(payload=kwargs, has_cb=_takes_cb):
            try:
                return pipe(**payload)
            except TypeError:
                # 老版本管线不认这两个参数 —— 去掉重试，进度条退化为按步数均分
                if has_cb:
                    payload.pop("callback_on_step_end", None)
                    payload.pop("callback_on_step_end_tensor_inputs", None)
                    prog["callback_unavailable"] = True
                    return pipe(**payload)
                raise

        prog["status"] = "running"
        prog["phase"] = "denoising"
        try:
            torch.cuda.reset_peak_memory_stats()
            result = await asyncio.get_running_loop().run_in_executor(None, _call)
            # 去噪走完了，但图还没好：VAE 解码 + PNG 编码 + base64 还在后面。
            # 以前这里就把 status 写成 done、pct 写 100，前端于是"卡在 100% 不动"。
            # 现在拆成两个阶段，进度条满格但文案说清楚在干什么。
            prog["phase"] = "decoding"
            prog["status"] = "decoding"
            prog["decode_started"] = time.time()
            prog["step"] = prog["total"]
            prog["steps_done"] = prog["total"]
            prog["pct"] = 100.0
            prog["eta_s"] = 0.0
        except torch.cuda.OutOfMemoryError:
            prog["status"] = "error"
            prog["error"] = "CUDA OOM"
            torch.cuda.empty_cache()
            raise HTTPException(507, "CUDA OOM: lower width/height or set QWEN_OFFLOAD=model and restart")
        except Exception as exc:                                 # noqa: BLE001
            prog["status"] = "error"
            prog["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            prog["finished_at"] = time.time()
            prog["elapsed_s"] = round(time.time() - t0, 2)
            if torch.cuda.is_available():
                global _peak_gib
                _peak_gib = max(_peak_gib, round(torch.cuda.max_memory_allocated() / 1024 ** 3, 2))
        elapsed = round(time.time() - t0, 2)
        items = []
        prog["status"] = "encoding"
        prog["phase"] = "encoding"
        prog["decode_s"] = round(time.time() - prog.get("decode_started", t0), 2)
        t_enc = time.time()
        for i, im in enumerate(result.images):
            if fmt in ("jpg", "jpeg") and im.mode == "RGBA":
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            buf = io.BytesIO()
            # compress_level=1：PNG 默认 6 级，在 1024² 上要多花几百毫秒，
            # 而对生成图来说这点压缩收益毫无意义。体积大约 +10%。
            im.save(buf, format="PNG" if fmt == "png" else fmt.upper(),
                    **({"compress_level": 1} if fmt == "png" else {}))
            items.append({
                "b64_json": _b64(buf.getvalue()),
                # 多图时每张的种子依次 +1（和 generator 的推进方式一致），
                # 这样每张图都能被单独复现
                "seed": int(seed) + i,
                "seed_given": bool(seed_given),
                "width": im.width, "height": im.height,
                "mode": im.mode, "elapsed_s": elapsed,
            })
        prog["status"] = "done"
        prog["phase"] = "done"
        prog["encode_s"] = round(time.time() - t_enc, 2)
        # 把真实耗时统计带回给调用方（每步均值 / 每步明细 / 排队与加载开销）
        if items:
            items[0]["timing"] = {
                "request_id": prog["request_id"],
                "total_s": elapsed,
                "prep_s": prep_s,
                "steps": prog["total"],
                "per_step_s": prog["per_step_s"],
                "durations": prog["durations"][-12:],
                "callback_ok": not prog["callback_unavailable"],
                # 去噪之后的两段：VAE 解码 + 图像编码。前端要能说清"100% 之后在等什么"
                "decode_s": prog.get("decode_s"),
                "encode_s": prog.get("encode_s"),
            }
        return items


def _valid_keys() -> List[str]:
    """当前所有可用的 key（主 key + QWEN_API_KEYS 里的额外 key，逗号/分号分隔）。"""
    raw = [API_KEY] + [k for k in re.split(r"[,;\s]+", EXTRA_KEYS) if k]
    seen, out = set(), []
    for k in raw:
        k = (k or "").strip()
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _key_ok(given: str) -> bool:
    """常量时间比较，避免时序侧信道。"""
    if not given:
        return False
    return any(secrets.compare_digest(given, k) for k in _valid_keys())


def _check_auth_request(request: Request):
    """统一守卫：/v1/*、进度接口与 /docs 系列都走它。

    三种带法（任一成立即可）：
      Cookie: <SESSION_COOKIE>=<token>   —— 浏览器登录后自动带上，JS 读不到（HttpOnly）
      Authorization: Bearer <key>        —— 脚本 / 上游服务
      ?key=<key>                         —— 浏览器直接跳转、<img>/<a> 这类发不了 header 的场景
    """
    if not API_KEY and not EXTRA_KEYS:
        return
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer ") and _key_ok(auth[7:].strip()):
        return
    if _key_ok(request.query_params.get("key", "")):
        return
    tok = request.cookies.get(SESSION_COOKIE)
    if tok and _session_valid(tok):
        return
    raise HTTPException(401, "需要鉴权：登录控制台、或带 Authorization: Bearer <key> / ?key=<key>")


def _session_valid(tok: str) -> bool:
    exp = SESSIONS.get(tok)
    if not exp:
        return False
    if exp < time.time():
        SESSIONS.pop(tok, None)
        return False
    return True


def _new_session() -> str:
    tok = secrets.token_urlsafe(32)
    SESSIONS[tok] = time.time() + SESSION_TTL
    # 顺手清过期
    now = time.time()
    for k in [k for k, v in SESSIONS.items() if v < now]:
        SESSIONS.pop(k, None)
    return tok


def _set_session_cookie(resp, tok: str):
    resp.set_cookie(SESSION_COOKIE, tok, max_age=SESSION_TTL, httponly=True,
                    samesite="strict", secure=COOKIE_SECURE, path="/")
    return resp


# FastAPI 依赖版本，给路由挂上就不用每个函数里手动调
def require_key(request: Request):
    _check_auth_request(request)


def _check_auth(request: Request):          # 兼容旧调用点
    _check_auth_request(request)


# --------------------------------------------------------------------------- #
# routes
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse)
async def index():
    """浏览器控制台（单页，无构建步骤）。

    是否把 key 注入页面由 QWEN_UI_KEY 决定（inject / auto / off）。
    inject 只适合自己用；分享镜像给别人时必须用 auto，否则打开页面就等于拿到 key。
    """
    page = os.path.join(UI_DIR, "index.html")
    if os.path.exists(page):
        html = open(page, encoding="utf-8").read()
        injected = API_KEY if UI_KEY_MODE == "inject" else ""
        html = html.replace("__QWEN_KEY_INJECT__", injected)
        html = html.replace("__QWEN_KEY_MODE__", UI_KEY_MODE)
        # 不注入模式下发个响应头，方便排障时确认模式
        return HTMLResponse(html, headers={"X-UI-Key-Mode": UI_KEY_MODE})
    return HTMLResponse(
        "<h1>Qwen-Image-2.1</h1><p>WebUI 文件缺失：%s</p>"
        "<p>接口文档：<a href='/docs'>/docs</a> · 服务状态：<a href='/health'>/health</a></p>"
        % page, status_code=200)


@app.get("/ui", response_class=HTMLResponse)
async def ui_alias():
    return await index()


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# 登录 / 登出：把 API Key 换成 HttpOnly Cookie 会话
# 这样浏览器端不需要（也拿不到）明文 key；JS 读不到 Cookie，XSS 也偷不走。
# --------------------------------------------------------------------------- #
@app.post("/v1/session")
async def create_session(request: Request):
    """用 API Key 换一个会话 Cookie。

    body: {"key": "<QWEN_API_KEY>"}   —— 主 key 或 QWEN_API_KEYS 里的任一 key 都行；
                                        没启用鉴权时可以不带
    """
    if not API_KEY and not EXTRA_KEYS:
        return {"ok": True, "auth_required": False, "message": "服务未启用鉴权"}
    body = {}
    try:
        body = await request.json()
    except Exception:                                                 # noqa: BLE001
        pass
    given = str(body.get("key") or request.headers.get("x-api-key") or "").strip()
    if not _key_ok(given):
        raise HTTPException(401, "API Key 不正确")
    tok = _new_session()
    return _set_session_cookie(
        JSONResponse({"ok": True, "expires_in_h": SESSION_TTL // 3600,
                      "cookie": SESSION_COOKIE, "httponly": True, "secure": COOKIE_SECURE}),
        tok)


@app.get("/v1/session")
async def read_session(request: Request):
    """看看当前浏览器有没有有效会话（前端用它决定要不要显示登录框）。"""
    if not API_KEY and not EXTRA_KEYS:
        return {"authenticated": True, "auth_required": False}
    tok = request.cookies.get(SESSION_COOKIE)
    if tok and _session_valid(tok):
        return {"authenticated": True, "auth_required": True,
                "expires_in_s": int(SESSIONS[tok] - time.time())}
    return {"authenticated": False, "auth_required": True}


@app.delete("/v1/session")
async def delete_session(request: Request):
    tok = request.cookies.get(SESSION_COOKIE)
    if tok:
        SESSIONS.pop(tok, None)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@app.get("/health")
async def health():
    ckpt = os.path.isdir(MODEL_DIR) and os.path.exists(os.path.join(MODEL_DIR, "model_index.json"))
    return {
        "status": "ok",
        "model": MODEL_VERSION,
        "loaded": _pipe is not None,
        "mode": MODE,
        "mock": _effective_mock(),
        "checkpoint": {"dir": MODEL_DIR, "present": bool(ckpt)},
        "dtype": DTYPE_NAME,
        "offload": OFFLOAD,
        "preload": PRELOAD,
        "load_error": _load_error,
        "peak_allocated_gib": _peak_gib,
        "queue_depth": _queue_depth,
        "auth_required": bool(API_KEY or EXTRA_KEYS),
        "ui_key_mode": UI_KEY_MODE,
        "session_ttl_h": SESSION_TTL // 3600,
        "active": _progress_view(next(
            (p for p in sorted(_progress.values(), key=lambda x: x["started"], reverse=True)
             if p["status"] in ("queued", "running")), None)),
        "gpu": gpu_info(),
    }


@app.get("/v1/models", dependencies=[Depends(require_key)])
async def models():
    return {"object": "list", "data": [{"id": MODEL_VERSION, "object": "model", "owned_by": "qwen"}]}


@app.post("/v1/admin/empty_cache", dependencies=[Depends(require_key)])
async def empty_cache(request: Request):
    """Give the allocator's cached blocks back to the driver (weights stay loaded).

    Useful before a big 2K run: the service is a long-lived process and the
    torch caching allocator otherwise keeps several GiB reserved.
    """
    _check_auth(request)
    freed = 0.0
    if torch.cuda.is_available():
        before = torch.cuda.memory_reserved() / 1024 ** 3
        torch.cuda.empty_cache()
        freed = round(before - torch.cuda.memory_reserved() / 1024 ** 3, 2)
    return {"freed_gib": freed, "gpu": gpu_info()}


def _derive_size(images: List["Image.Image"], budget: int) -> tuple:
    """按官方实现从参考图推导输出尺寸（等价于让管线自己算，但我们要提前知道好做显存预检）。

    逐字对齐 diffusers 源码（pipeline_qwenimage21.py L148-157）：
        width  = math.sqrt(target_area * ratio)
        height = width / ratio          # 用**未取整**的 width
        width  = round(width / 32) * 32
        height = round(height / 32) * 32
    两个坑：① 取整是 round 到 32，不是 floor 到 16；
          ② 高要用未取整的宽反算，拿取整后的宽会偏。
    实测对照见 tools/check_size_formula.py（7/7 一致：768×1024+1024 → 896×1184 等）。
    """
    base = images[-1].size                       # 管线用最后一张定比例
    ratio = base[0] / base[1]
    area = float(budget) * float(budget)
    raw_w = (area * ratio) ** 0.5
    raw_h = raw_w / ratio
    return round(raw_w / 32) * 32, round(raw_h / 32) * 32


async def _parse_gen_request(request: Request) -> Dict[str, Any]:
    """把两种请求体（JSON / multipart）统一解析成内部 req —— 一个入口两种用法。"""
    ctype = (request.headers.get("content-type") or "").lower()
    rid_hdr = request.headers.get("x-request-id")
    images_in: List[Image.Image] = []
    neg = None
    gscale = None

    if ctype.startswith("multipart/form-data"):
        f = await request.form()

        def g(name, default=None):
            v = f.get(name)
            return default if v in (None, "") else v

        prompt = str(f.get("prompt") or "")
        steps = int(g("num_inference_steps", 40))
        seed = int(g("seed")) if g("seed") is not None else None
        output_format = str(g("output_format", "png"))
        transparent = str(g("transparent", "")).lower() in ("1", "true", "on", "yes")
        width = int(g("width")) if g("width") is not None else None
        height = int(g("height")) if g("height") is not None else None
        outres = int(g("output_resolution")) if g("output_resolution") is not None else None
        aspect = g("aspect_ratio")
        # 这两个以前只在 JSON 分支解析，multipart 会静默丢掉 → 两条路径行为不一致。
        neg = g("negative_prompt")
        # guidance_scale 是常见叫法，但管线实际参数名是 true_cfg_scale；两个都收。
        _gs = g("true_cfg_scale") or g("guidance_scale")
        gscale = float(_gs) if _gs is not None else None
        request_id = str(g("request_id") or "") or rid_hdr
        for key in ("image", "image[]"):
            for up in f.getlist(key):
                if hasattr(up, "read"):
                    raw = await up.read()
                    if raw:
                        images_in.append(Image.open(io.BytesIO(raw)).convert("RGBA"))
    else:
        b = await request.json()
        prompt = b.get("prompt")
        steps = int(b.get("num_inference_steps", 40))
        seed = b.get("seed")
        output_format = b.get("output_format", "png")
        transparent = bool(b.get("transparent", False))
        width, height = b.get("width"), b.get("height")
        outres = b.get("output_resolution")
        aspect = b.get("aspect_ratio")
        request_id = b.get("request_id") or rid_hdr
        neg = b.get("negative_prompt")
        gscale = b.get("guidance_scale")
        for b64 in (b.get("image_b64") or []):
            try:
                if isinstance(b64, str) and b64.startswith("data:"):
                    b64 = b64.split(",", 1)[1]
                images_in.append(Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGBA"))
            except Exception:                                        # noqa: BLE001
                raise HTTPException(400, "image_b64 里有无法解码的图片")

    if not prompt:
        raise HTTPException(400, "prompt is required")

    # ── 尺寸：分叉的判据是"有没有参考图"，不是"用户选了哪个 Tab" ──
    explicit = bool(width or height) or (aspect in ASPECT_RATIOS)
    if aspect in ASPECT_RATIOS:
        width, height = ASPECT_RATIOS[aspect]
    if not images_in:
        # 纯文本生成：没给尺寸就用官方默认 2K
        if not (width and height):
            width, height = _resolve_size(width, height, None, None)
    else:
        if not (width and height):
            # 有参考图又没指定尺寸 → 自己按官方公式推导。
            # 不能留给管线推导：显存预检要先知道尺寸，否则 None 会炸。
            width, height = _derive_size(images_in, int(outres or 1024))
            explicit = True
    # 只给了一边（只填 width 或只填 height）也要补成完整一对：预检要乘、管线也要乘，
    # 半截尺寸会跑到模型内部才炸成 NoneType。缺的那边按官方做法补——有参考图就用它的
    # 宽高比推另一边，没有就补成方图，最后统一 32 对齐（管线要求 32 的倍数）。
    if bool(width) != bool(height):
        ratio = (images_in[-1].size[0] / images_in[-1].size[1]) if images_in else 1.0
        if width:
            raw_w, raw_h = float(width), float(width) / ratio
        else:
            raw_w = float(height) * ratio
            raw_h = float(height)
        width = round(raw_w / 32) * 32
        height = round(raw_h / 32) * 32
        explicit = True

    return {
        "prompt": prompt, "width": width, "height": height,
        "explicit_size": bool(images_in),        # 有图时一律显式传宽高（值来自推导或用户）
        "num_inference_steps": steps, "seed": seed,
        "output_format": output_format, "transparent": transparent,
        "guidance_scale": gscale, "negative_prompt": neg,
        "output_resolution": outres, "images": images_in, "request_id": request_id,
    }


@app.post("/v1/images/generations", dependencies=[Depends(require_key)])
async def generations(request: Request):
    """统一入口：`image` 可选。

    底层是同一个管线（`QwenImage21Pipeline`）：传了 `image` 就是条件生成
    （官方叫 Image Editing / multi-subject composition），不传就是纯文本生成。
    所以这里**一个端点吃两种用法**，不再按"文生图/编辑"分家。

    请求体两种都收：
      · `multipart/form-data` —— 推荐；`prompt` + 可选的重复 `image` 字段（≤10 张）
      · `application/json`    —— 兼容；参考图放 `image_b64`（base64 数组，可带 data: 前缀）
    """
    global _queue_depth
    _check_auth(request)
    req = await _parse_gen_request(request)
    _queue_depth += 1
    items = await _generate(req)
    rid = items[0].get("timing", {}).get("request_id")
    return JSONResponse({"created": int(time.time()), "model": MODEL_VERSION,
                         "size": f"{items[0]['width']}x{items[0]['height']}", "data": items},
                        headers={"X-Request-Id": rid} if rid else None)


@app.post("/v1/images/edits", dependencies=[Depends(require_key)])
async def edits(request: Request):
    """**保留但已不是必需** —— 与 `/v1/images/generations` 是同一个实现，只是历史上给它俩起了
    两个名字。新代码请统一用 `/v1/images/generations`（`image` 可选）。

    留着它是因为：① 老客户端已经在用；② "编辑"这个词对使用者更直观。
    两条路径都走 `_parse_gen_request`，行为完全一致。
    """
    return await generations(request)


async def _run_job(job_id: str, req: Dict[str, Any]):
    _jobs[job_id]["status"] = "running"
    try:
        items = await _generate(req)
        _jobs[job_id]["result"] = items
        _jobs[job_id]["status"] = "succeeded"
    except HTTPException as exc:
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = {"code": exc.status_code, "message": exc.detail}
    except Exception as exc:                                   # noqa: BLE001
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = {"code": 500, "message": f"{type(exc).__name__}: {exc}"}
    finally:
        _jobs[job_id]["finished_at"] = int(time.time())


@app.post("/v1/jobs", status_code=202, dependencies=[Depends(require_key)])
async def create_job(request: Request, tasks: BackgroundTasks):
    """Async submit, for services that prefer polling over long HTTP waits."""
    global _queue_depth
    _check_auth(request)
    if _queue_depth + sum(1 for j in _jobs.values() if j["status"] in ("queued", "running")) >= MAX_QUEUE:
        raise HTTPException(429, "queue full")
    body = await request.json()
    prompt = body.get("prompt")
    if not prompt:
        raise HTTPException(400, "prompt is required")
    width, height = _resolve_size(body.get("width"), body.get("height"),
                                  body.get("size"), body.get("aspect_ratio"))
    req = {
        "prompt": prompt, "width": width, "height": height,
        "num_inference_steps": int(body.get("num_inference_steps", 40)),
        "seed": body.get("seed"), "output_format": body.get("output_format", "png"),
        "transparent": body.get("transparent", False),
        "guidance_scale": body.get("guidance_scale"),
        "negative_prompt": body.get("negative_prompt"),
    }
    job_id = "job_" + uuid.uuid4().hex[:16]
    req["request_id"] = job_id                      # 用 job_id 当进度键，前端可直接轮询
    _jobs[job_id] = {"id": job_id, "status": "queued", "created_at": int(time.time()),
                     "request_id": job_id,
                     "request": {k: v for k, v in req.items() if not k.startswith("_")}}
    _queue_depth += 1
    tasks.add_task(_run_job, job_id, req)
    return {"id": job_id, "status": "queued"}


@app.get("/v1/jobs/{job_id}", dependencies=[Depends(require_key)])
async def get_job(job_id: str, request: Request):
    _check_auth(request)
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


@app.delete("/v1/jobs/{job_id}", dependencies=[Depends(require_key)])
async def cancel_job(job_id: str, request: Request):
    _check_auth(request)
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if job["status"] == "queued":
        job["status"] = "canceled"
    return job


@app.get("/v1/jobs", dependencies=[Depends(require_key)])
async def list_jobs(request: Request, limit: int = 20):
    _check_auth(request)
    return {"data": list(_jobs.values())[-limit:]}


# --------------------------------------------------------------------------- #
# 进度查询：前端在生成期间轮询它，拿到真实步数 / 每步耗时 / ETA
# --------------------------------------------------------------------------- #
@app.get("/v1/progress", dependencies=[Depends(require_key)])
async def progress_list():
    """当前/最近几次任务的进度（按开始时间倒序）。"""
    items = [_progress_view(_progress[k]) for k in
             sorted(_progress, key=lambda k: _progress[k]["started"], reverse=True)[:10]]
    return {"data": items}


@app.get("/v1/progress/{request_id}", dependencies=[Depends(require_key)])
async def progress_one(request_id: str):
    view = _progress_view(_progress.get(request_id))
    if view is None:
        raise HTTPException(404, "unknown request_id")
    return view


# --------------------------------------------------------------------------- #
# 文档端点（内置的已关掉，这里自己实现以便纳入鉴权）
# Swagger 的 openapi_url 直接带上 key，这样 ?key=xxx 打开后文档能正常加载
# --------------------------------------------------------------------------- #
def _spec_url() -> str:
    ks = _valid_keys()
    if not ks:
        return "/openapi.json"
    return "/openapi.json?key=" + quote(ks[0], safe="")


@app.get("/openapi.json", include_in_schema=False)
async def openapi_spec(_: None = Depends(require_key)):
    return JSONResponse(get_openapi(title=app.title, version=app.version, routes=app.routes))


@app.get("/docs", include_in_schema=False)
async def swagger_docs(_: None = Depends(require_key)):
    return get_swagger_ui_html(openapi_url=_spec_url(), title=app.title + " · docs")


@app.get("/redoc", include_in_schema=False)
async def redoc_docs(_: None = Depends(require_key)):
    return get_redoc_html(openapi_url=_spec_url(), title=app.title + " · redoc")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info", timeout_keep_alive=120)
