#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Identity compensation + expression suite, then one self-contained HTML report.

  python tools\qwen_report.py            # 用已有产物直接出报告
  python tools\qwen_report.py --run      # 先跑表情专项（需要隧道在跑）

Output: D:\\workspace\\dsh-default\\tmp\\qwen_test\\report.html  (所有图片内嵌 base64)
"""
import argparse
import base64
import io
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "service"))
sys.path.insert(0, _HERE)
from face_fix import FaceFixer, detect_face_box   # noqa: E402
from qwen_report_parts import CSS, JS_WIDGET      # noqa: E402
import config as C                                # noqa: E402

ROOT = C.TEST_DATA
C.ensure(C.REPORT)
FIXDIR = os.path.join(ROOT, "fix")
EXPRDIR = os.path.join(ROOT, "expr")
W, H = 1088, 1600
FACE_BOX = (int(W * 0.22), int(H * 0.03), int(W * 0.78), int(H * 0.30))


# ----------------------------------------------------------------- 指标
def gray(im):
    return np.asarray(im.convert("L")).astype(np.float32) / 255.0


def gauss(x, k=11, s=1.5):
    return cv2.GaussianBlur(x, (k, k), s)


def ssim(a, b):
    a, b = a.astype(np.float64), b.astype(np.float64)
    C1, C2 = 0.01 ** 2, 0.03 ** 2
    ma, mb = gauss(a), gauss(b)
    sa, sb = gauss(a * a) - ma ** 2, gauss(b * b) - mb ** 2
    sab = gauss(a * b) - ma * mb
    return float((((2 * ma * mb + C1) * (2 * sab + C2)) /
                  ((ma ** 2 + mb ** 2 + C1) * (sa + sb + C2))).mean())


def region_mad(a, b, box):
    x0, y0, x1, y1 = box
    return float(np.abs(a[y0:y1, x0:x1] - b[y0:y1, x0:x1]).mean())


# ----------------------------------------------------------------- 数据准备
def load_src():
    return Image.open(os.path.join(ROOT, "input_edit.jpg")).convert("RGB").resize((W, H), Image.LANCZOS)


def run_expression_suite(src, fx, expr_prompts):
    """在最好的姿势产物的基础上做表情专项：一步一改，前后各量一次。"""
    os.makedirs(EXPRDIR, exist_ok=True)
    import requests
    for i in range(120):
        try:
            h = requests.get(BASE + "/health", timeout=10).json()
            if h.get("loaded"):
                print(f"service ready, gpu free {h['gpu']['free_gb']} GiB")
                break
        except Exception:                                        # noqa: BLE001
            pass
        import time
        time.sleep(10)
    else:
        raise SystemExit("service not ready")
    requests.post(BASE + "/v1/admin/empty_cache", timeout=60)

    base_png = os.path.join(ROOT, "anchor", "A_single_ref_1pose.png")
    base = Image.open(base_png).convert("RGB")
    buf = io.BytesIO()
    base.save(buf, format="PNG")
    payload = buf.getvalue()

    src_g = gray(src)
    rows = []
    for key, (label, prompt) in expr_prompts.items():
        r = requests.post(BASE + "/v1/images/edits",
                          data={"prompt": prompt, "num_inference_steps": "35", "seed": "22"},
                          files=[("image", ("base.png", payload, "image/png"))], timeout=3600)
        if r.status_code != 200:
            print(f"[{key}] FAIL {r.status_code} {r.text[:120]}")
            continue
        raw = base64.b64decode(r.json()["data"][0]["b64_json"])
        p = os.path.join(EXPRDIR, f"{key}.png")
        open(p, "wb").write(raw)
        ed = Image.open(io.BytesIO(raw)).convert("RGB").resize((W, H), Image.LANCZOS)
        fixed, info = fx.paste(ed, feather=0.16, strength=1.0, min_confidence=-1.0)
        fp = os.path.join(EXPRDIR, f"{key}_fixed.png")
        fixed.save(fp)
        rows.append({
            "key": key, "label": label, "prompt": prompt,
            "file": p, "fixed_file": fp,
            "face_mad_before": round(region_mad(src_g, gray(ed), FACE_BOX), 4),
            "face_mad_after": round(region_mad(src_g, gray(fixed), FACE_BOX), 4),
            "ssim_before": round(ssim(src_g, gray(ed)), 4),
            "ssim_after": round(ssim(src_g, gray(fixed)), 4),
            "confidence": info.get("confidence"), "method": info.get("method"),
        })
        print(f"[{key}] face_mad {rows[-1]['face_mad_before']} -> {rows[-1]['face_mad_after']} "
              f"(conf {info.get('confidence')})")
    json.dump(rows, open(os.path.join(EXPRDIR, "expr_metrics.json"), "w"), ensure_ascii=False, indent=1)
    return rows


def compare_expr(files, out_path):
    """把四个表情变体横排成一张图，用来判断模型是否真的换了表情（而不是同一张重绘）。"""
    ims = [Image.open(f).convert("RGB") for f in files]
    cell = 300
    sheet = Image.new("RGB", (cell * len(ims), cell), (16, 16, 20))
    for i, im in enumerate(ims):
        sheet.paste(im.resize((cell, cell), Image.LANCZOS), (i * cell, 0))
    sheet.save(out_path)
    return out_path


# ----------------------------------------------------------------- 报告
def load_json_any(path):
    """JSON 可能由不同 locale 的进程写出，逐个编码试。"""
    raw = open(path, "rb").read()
    for enc in ("utf-8", "utf-8-sig", "gbk", "cp936"):
        try:
            return json.loads(raw.decode(enc))
        except Exception:                                       # noqa: BLE001
            continue
    return json.loads(raw.decode("utf-8", "replace"))


def b64(path, max_w=None):
    im = Image.open(path).convert("RGB")
    if max_w and im.width > max_w:
        im = im.resize((max_w, int(im.height * max_w / im.width)), Image.LANCZOS)
    b = io.BytesIO()
    im.save(b, format="JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()


def png_url(path, max_w=None):
    """无损 PNG data-URI：交互式贴回要在浏览器里做像素级合成，JPEG 会引入偏差。"""
    im = Image.open(path).convert("RGB")
    if max_w and im.width > max_w:
        im = im.resize((max_w, int(im.height * max_w / im.width)), Image.LANCZOS)
    b = io.BytesIO()
    im.save(b, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()


def build_html(src, fixer_rows, expr_rows, fx, out_path, expr_strip=None):
    src_url = b64(os.path.join(ROOT, "input_edit.jpg"), 560)

    def fmt(v, before):
        cls = "good" if v < before else "bad"
        return f'<td class="{cls}">{v}</td>'

    fix_rows_html = "".join(
        f"<tr><td>{r['name']}</td><td>{r['before_face_mad']}</td>"
        f"{fmt(r['after_face_mad'], r['before_face_mad'])}"
        f"<td style='color:var(--good)'>{r['before_face_mad'] - r['after_face_mad']:+.4f}</td></tr>"
        for r in fixer_rows)

    expr_table = "".join(
        f"<tr><td>{r['label']}</td><td>{r['face_mad_before']}</td>"
        f"{fmt(r['face_mad_after'], r['face_mad_before'])}<td>{r['ssim_before']}</td>"
        f"<td>{r['ssim_after']}</td></tr>" for r in expr_rows)

    def card(row):
        return f"""
      <div class="card">
        <div class="head"><span class="tag">{row['label']}</span>
          <span class="conf">局部相关 conf {row.get('confidence')}</span></div>
        <div class="tri">
          <figure><img src="{src_url}" loading="lazy"><figcaption>0 原图（身份基准）</figcaption></figure>
          <figure><img src="{b64(row['file'], 460)}" loading="lazy"><figcaption>1 模型输出 · 人脸漂移 {row['face_mad_before']}</figcaption></figure>
          <figure><img src="{b64(row['fixed_file'], 460)}" loading="lazy"><figcaption>2 回贴补偿 · 人脸漂移 {row['face_mad_after']}</figcaption></figure>
        </div>
        <p class="prompt"><b>表情指令</b>：{row['prompt']}</p>
      </div>"""

    expr_cards = "\n".join(card(r) for r in expr_rows)
    strip_html = ""
    if expr_strip and os.path.exists(expr_strip):
        strip_html = (f'<div class="panel" style="margin:14px 0 20px">'
                      f'<img src="{b64(expr_strip, 1200)}" style="width:100%;border-radius:8px">'
                      f'<div class="kbd" style="padding-top:8px">四个表情变体横排（同一姿势、同一 seed）：'
                      f'左到右 = 羞涩微笑 / 惊讶 / 闭眼微笑 / 侧头看向别处</div></div>')

    example_png = os.path.join(ROOT, fixer_rows[0]["file"] if "file" in fixer_rows[0] else
                               os.path.join(ROOT, "anchor", "A_single_ref_1pose.png"))
    ed_url = png_url(example_png, 1088)
    src_png_url = png_url(os.path.join(ROOT, "input_edit.jpg"), 1088)
    box = fx.box

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>Qwen-Image-2.1 编辑链 · 人脸补偿 + 表情专项</title>
<style>{CSS}</style>
{JS_WIDGET}
</head><body>
<header>
  <h1>Qwen-Image-2.1 编辑链 · 人脸补偿与表情专项</h1>
  <div class="sub">4090 48G · 全 BF16 常驻 · 单步 35 steps ≈ 24s · seed 22 · 1088×1600 竖构图输入 · 指标越低越接近原图</div>
</header>
<div class="wrap">

  <h2>一、问题定义</h2>
  <div class="note">
    上一轮结论：这条编辑链<b>每一步都会重绘整张图，包括脸</b>。只要求改姿势的那一步，人脸区域像素漂移 0.180，
    和整图漂移 0.177 一样大；四步链跑完与原始输入的 SSIM 只剩 0.138。提示词里写 KEEP 段落（长句 vs 清单式）
    数值几乎逐位重合，<b>措辞锁不住人脸</b>。本页验证两条补救路线：链路之外把人脸贴回来，以及把表情拆成单步。
  </div>

  <h2>二、回贴补偿 <span class="badge">有效，但只能固定位置</span></h2>
  <div class="note">
    做法：把源图人脸按羽化椭圆蒙版贴回编辑帧。难点全在<b>定位</b>，三种自动方案实测全败：
    <br>· <b>Haar 人脸检测</b>：为真人训练，anime 帧上误检严重——实测把整块上半身 (174,0,731,552)
      和背景花丛 (885,348,1018,492) 当成脸。
    <br>· <b>归一化模板匹配</b>：脸周围是书架和蓝墙，换姿势后背景全变，最高分只有 0.44~0.63，位置整体偏到眼睛下方。
    <br>· <b>肤色连通域</b>：整图蓝色调，HSV 肤色掩膜几乎为空，偶尔凑出的候选还是手臂。
    <br>所以本页数值用的是<b>固定位置贴回</b>：按源图检出的脸框 (364,303,574,530) 原位贴回。
    对头部位置基本没变的帧有效（下表每一行都改善，幅度 12%~21%），对头部大位移的帧会贴错——
    第三部分的手动对齐工具就是给这种情况用的。
  </div>
  <table>
    <tr><th>编辑产物</th><th>人脸漂移（补偿前）</th><th>补偿后</th><th>改善</th></tr>
    {fix_rows_html}
  </table>

  <h2>三、手动对齐工具（浏览器内实时合成）</h2>
  <div class="note">
    自动定位不可靠，这一节改成人工点选：在左边画布上<b>拖拽框出编辑图里人脸的位置</b>，右边实时出合成结果。
    羽化半径可调，满意后点「下载 PNG」。框的坐标会写进地址栏 <code>#box=x,y,w,h</code>，
    把它发我或自己带上即可复现同一位置。
  </div>
  <div class="tools">
    <div class="panel">
      <div class="tag">① 在编辑图上框选人脸</div>
      <div class="kbd" style="margin:6px 0 10px">当前：<span id="boxinfo"></span></div>
      <canvas id="cv"></canvas>
      <div class="row">
        <button id="reset" class="ghost">重置为源图脸框</button>
        <label class="kbd">羽化 <input id="feather" type="range" min="0.02" max="0.45" step="0.01" value="0.16"></label>
      </div>
    </div>
    <div class="panel">
      <div class="tag">② 合成结果</div>
      <div class="kbd" style="margin:6px 0 10px">源图人脸在新位置上像素级贴回 + 椭圆羽化</div>
      <canvas id="out"></canvas>
      <div class="row"><button id="save">下载 PNG</button></div>
    </div>
  </div>

  <h2>四、表情专项：一步一改 <span class="badge warn">数值高度雷同，需人眼复核</span></h2>
  <div class="note">
    在姿势产物基础上单独改表情，一次只改一个维度，35 步，同 seed。四个变体的量化指标几乎完全一致
    （0.2226 / 0.2222 / 0.2221 / 0.2219），说明模型对这四个不同的表情指令做出了<b>同一种强度的重绘</b>，
    而不是四张有区别的表情。下面的横排图和卡片用来人眼确认实际差别。
  </div>
  {strip_html}
  <table>
    <tr><th>表情</th><th>人脸漂移（前）</th><th>补偿后</th><th>SSIM（前）</th><th>SSIM（后）</th></tr>
    {expr_table}
  </table>
  {expr_cards}

</div>
<script>
const SOURCE_URL = "{src_png_url}";
const EDITED_URL = "{ed_url}";
const DEFAULT_BOX = [{box[0]}, {box[1]}, {box[2] - box[0]}, {box[3] - box[1]}];
box = {{x: DEFAULT_BOX[0], y: DEFAULT_BOX[1], w: DEFAULT_BOX[2], h: DEFAULT_BOX[3]}};
(function () {{
  const m = location.hash.match(/box=(\\d+),(\\d+),(\\d+),(\\d+)/);
  if (m) box = {{x: +m[1], y: +m[2], w: +m[3], h: +m[4]}};
  start();
}})();
</script>
</body></html>"""
    open(out_path, "w", encoding="utf-8").write(html)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="先跑表情专项（需要隧道）")
    a = ap.parse_args()

    src = load_src()
    box, det = detect_face_box(src)
    fx = FaceFixer(src, box=box, manual_face=det)
    print("face box:", box, "haar:", det)

    # ---- 补偿：过一遍此前所有编辑产物
    targets = [
        ("chain/chainA_pose_expr_hands_cam/4_camera.png", "四步链 A 终帧"),
        ("chain/chainB_clean_keep_blocks/4_hands.png", "四步链 B 终帧"),
        ("anchor/A_single_ref_1pose.png", "姿势步（单参考图）"),
        ("anchor/B_anchor_orig_1pose.png", "姿势步（原图锚定）"),
        ("nsfw_L1_open_pose.png", "姿势阶梯 L1"),
        ("poseB_crouch_symmetric_22.png", "蹲姿 seed22"),
        ("edit_crouching_2k.png", "蹲姿 v2"),
    ]
    src_g = gray(src)
    fixer_rows = []
    os.makedirs(FIXDIR, exist_ok=True)
    for rel, label in targets:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        ed = Image.open(p).convert("RGB").resize((W, H), Image.LANCZOS)
        fixed, info = fx.paste(ed, feather=0.16, strength=1.0, min_confidence=-1.0)
        fixed.save(os.path.join(FIXDIR, os.path.basename(rel).replace(".png", "_fixed.png")))
        fixer_rows.append({
            "name": label,
            "before_face_mad": round(region_mad(src_g, gray(ed), FACE_BOX), 4),
            "after_face_mad": round(region_mad(src_g, gray(fixed), FACE_BOX), 4),
            "confidence": info.get("confidence"), "method": info.get("method"),
        })
        print(f"[fix] {label:22s} {fixer_rows[-1]['before_face_mad']} -> {fixer_rows[-1]['after_face_mad']} "
              f"conf={info.get('confidence')}")

    # ---- 表情专项
    expr_rows = []
    if a.run:
        prompts = {
            "E1_shy_smile": ("羞涩微笑", "Keep the pose and the camera exactly as they are. Change only her "
                                          "facial expression to a shy bashful smile with slightly blushing "
                                          "cheeks and eyes glancing at the viewer. Keep the same face and "
                                          "identity, same hair, same dress, same room, same lighting."),
            "E2_surprised": ("惊讶", "Keep the pose and the camera exactly as they are. Change only her facial "
                                     "expression to a surprised expression: raised eyebrows, wide eyes, lips "
                                     "slightly parted. Keep the same face and identity, same hair, same "
                                     "dress, same room, same lighting."),
            "E3_eyes_closed": ("闭眼微笑", "Keep the pose and the camera exactly as they are. Change only her "
                                           "facial expression: eyes peacefully closed, gentle soft smile. "
                                           "Keep the same face and identity, same hair, same dress, same "
                                           "room, same lighting."),
            "E4_looking_away": ("侧头看向别处", "Keep the pose and the camera exactly as they are. Change only "
                                                "her head and eyes: head turned slightly to her right, gaze "
                                                "directed away from the viewer. Keep the same face and "
                                                "identity, same hair, same dress, same room, same lighting."),
        }
        expr_rows = run_expression_suite(src, fx, prompts)
        if expr_rows:
            compare_expr([r["file"] for r in expr_rows], os.path.join(ROOT, "expr_strip.png"))
    else:
        p = os.path.join(EXPRDIR, "expr_metrics.json")
        if os.path.exists(p):
            expr_rows = load_json_any(p)
        strip = os.path.join(ROOT, "expr_strip.png")
        if expr_rows and not os.path.exists(strip):
            compare_expr([r["file"] for r in expr_rows], strip)

    out = build_html(src, fixer_rows, expr_rows, fx, os.path.join(C.REPORT, "face-fix-report.html"),
                     expr_strip=os.path.join(ROOT, "expr_strip.png"))
    print("\nreport ->", out)


if __name__ == "__main__":
    main()
