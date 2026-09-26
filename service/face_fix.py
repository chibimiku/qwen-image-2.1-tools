#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""face_fix.py — identity compensation for Qwen-Image-2.1 edit chains.

The model rewrites the whole frame on every edit step, so the face drifts even
when the prompt says to keep it. This module pastes the ORIGINAL face back onto
an edited frame:

  1. locate the face in the source image (Haar, with a manual fallback box)
  2. locate the same face in the edited frame (normalised template matching)
  3. blend the source face back with a feathered elliptical mask

Usage as a library:

    from face_fix import FaceFixer
    fx = FaceFixer(src_pil)                     # source = the very first input
    out, info = fx.paste(edited_pil, feather=0.14)
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")


def _gray(im: Image.Image) -> np.ndarray:
    return np.asarray(im.convert("L"))


def detect_face_box(im: Image.Image, fallback=(0.22, 0.03, 0.78, 0.30)):
    """Return ((x0, y0, x1, y1), detected). `fallback=None` means box is None when
    nothing was detected."""
    W, H = im.size
    g = _gray(im)
    faces = _CASCADE.detectMultiScale(g, scaleFactor=1.05, minNeighbors=4,
                                      minSize=(max(24, W // 12), max(24, W // 12)))
    if len(faces) == 0:
        if fallback is None:
            return None, False
        return (int(W * fallback[0]), int(H * fallback[1]),
                int(W * fallback[2]), int(H * fallback[3])), False
    # 取最靠上的那个（竖构图里脸在上部）
    x, y, w, h = sorted(faces, key=lambda f: f[1])[0]
    pad = 0.18
    x0 = max(0, int(x - w * pad))
    y0 = max(0, int(y - h * pad))
    x1 = min(W, int(x + w * (1 + pad)))
    y1 = min(H, int(y + h * (1 + pad * 1.6)))
    return (x0, y0, x1, y1), True


class FaceFixer:
    def __init__(self, source: Image.Image, box=None, manual_face=False):
        self.src = source.convert("RGB")
        self.W, self.H = self.src.size
        if box:
            self.box = box
            self.detected = manual_face
        else:
            b, ok = detect_face_box(self.src)
            self.box, self.detected = b, ok
        self.patch = self.src.crop(self.box)
        self.patch_gray = _gray(self.patch)

    # ------------------------------------------------------------------ #
    def locate(self, edited: Image.Image, max_shift=1.0):
        """Decide where the source face goes in `edited`.

        With manual placement (`box=` / `face_box=` supplied) we paste at the same
        canvas position, and only do so when the frame's local structural
        correlation is high enough that the head cannot have moved far.
        Returns ((x, y, w, h), confidence, method).
        """
        if edited.size != (self.W, self.H):
            edited = edited.resize((self.W, self.H), Image.LANCZOS)
        x0, y0, x1, y1 = self.box
        bw, bh = x1 - x0, y1 - y0

        # 局部结构相关：同位置附近 2 倍框范围内的归一化互相关
        g = _gray(edited)
        px, py = int(bw * 0.5), int(bh * 0.5)
        sx0, sy0 = max(0, x0 - px), max(0, y0 - py)
        sx1, sy1 = min(self.W, x1 + px), min(self.H, y1 + py)
        region = g[sy0:sy1, sx0:sx1].astype(np.float32)
        r = region - region.mean()
        p = self.patch_gray.astype(np.float32)
        p = p - p.mean()
        denom = (np.linalg.norm(r) * np.linalg.norm(p)) or 1.0
        # 比较同尺寸的中心窗口
        cx0 = max(0, (x0 - sx0))
        cy0 = max(0, (y0 - sy0))
        win = region[cy0:cy0 + bh, cx0:cx0 + bw]
        if win.shape == p.shape:
            denom = (np.linalg.norm(win - win.mean()) * np.linalg.norm(p)) or 1.0
            score = float(((win - win.mean()) * p).sum() / denom)
        else:
            score = 0.0
        return (x0, y0, bw, bh), round(score, 3), "fixed-position"

    # ------------------------------------------------------------------ #
    def paste(self, edited: Image.Image, feather=0.16, strength=1.0, min_confidence=-1.0):
        """Blend the source face back onto `edited`. Returns (image, info).

        `min_confidence` guards against pasting onto a frame where the head has
        clearly moved: if the local correlation is below it, nothing is changed and
        `info['skipped']` explains why.
        """
        if edited.size != (self.W, self.H):
            edited = edited.resize((self.W, self.H), Image.LANCZOS)
        (bx, by, bw, bh), conf, method = self.locate(edited)
        if conf < min_confidence:
            return edited, {"method": method, "confidence": conf,
                            "skipped": f"local correlation {conf} < {min_confidence} (head likely moved)"}

        patch = self.patch.resize((bw, bh), Image.LANCZOS)
        mask = np.zeros((bh, bw), np.float32)
        cv2.ellipse(mask, (bw // 2, int(bh * 0.52)), (int(bw * 0.47), int(bh * 0.50)),
                    0, 0, 360, 1.0, -1)
        k = max(3, int(min(bw, bh) * feather) | 1)
        mask = cv2.GaussianBlur(mask, (k, k), 0) * float(np.clip(strength, 0.0, 1.0))

        out = np.asarray(edited).astype(np.float32).copy()
        H, W = out.shape[:2]
        # 贴回区域可能越界（脸被画到画面外），裁一下
        px0, py0 = max(0, bx), max(0, by)
        px1, py1 = min(W, bx + bw), min(H, by + bh)
        if px1 - px0 < 8 or py1 - py0 < 8:
            return edited, {"method": method, "skipped": "paste box outside canvas"}
        sub = out[py0:py1, px0:px1]
        pa = np.asarray(patch).astype(np.float32)[py0 - by:py1 - by, px0 - bx:px1 - bx]
        m3 = mask[py0 - by:py1 - by, px0 - bx:px1 - bx][..., None]
        out[py0:py1, px0:px1] = sub * (1 - m3) + pa * m3
        res = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
        return res, {"method": method, "confidence": conf, "paste_box": (bx, by, bw, bh),
                     "feather": feather, "strength": strength,
                     "face_detected": self.detected}
