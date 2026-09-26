#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build the instruction-response matrix report (HTML + tables) from matrix_results.json.

    python tools/matrix_report.py
"""
import base64
import io
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C                                                    # noqa: E402

OUT = os.path.join(C.TEST_DATA, "matrix")
SHEETS = os.path.join(OUT, "sheets")
C.ensure(C.REPORT, SHEETS)


# ------------------------------------------------------------------ 指标
def gray(path_or_im):
    im = path_or_im if isinstance(path_or_im, Image.Image) else Image.open(path_or_im)
    return np.asarray(im.convert("L").resize((C.W, C.H))).astype(np.float32) / 255.0


def rgb(path):
    return np.asarray(Image.open(path).convert("RGB").resize((C.W, C.H))).astype(np.float32) / 255.0


def region_delta(a, b, box):
    x0, y0, x1, y1 = box
    return float(np.abs(a[y0:y1, x0:x1] - b[y0:y1, x0:x1]).mean())


def edge_delta(a, b):
    d = np.abs(a - b)
    return float(np.concatenate([d[:100, :].ravel(), d[-100:, :].ravel(),
                                 d[:, :80].ravel(), d[:, -80:].ravel()]).mean())


def load_matrix():
    p = os.path.join(OUT, "matrix_results.json")
    return json.loads(open(p, "rb").read().decode("utf-8", "replace"))


def build_rows(results):
    src = gray(C.INPUT_EDIT)
    base = gray(os.path.join(OUT, "B0_baseline.png"))
    boxes = {k: C.px(v) for k, v in C.REGIONS.items()}
    # 目标区域之外的“其余”用三条参考带（上/中/下）里的非目标部分近似
    rows = []
    for r in results:
        if not r.get("ok"):
            rows.append({**r, "verdict": "fail"})
            continue
        im = gray(r["file"])
        d = np.abs(base - im)
        face = region_delta(base, im, boxes["face"])
        torso = region_delta(base, im, boxes["torso"])
        edge = edge_delta(base, im)
        mad_all = float(d.mean())
        r = {**r, "face_d": round(face, 4), "torso_d": round(torso, 4), "edge_d": round(edge, 4),
             "mad_vs_base": round(mad_all, 4),
             "redraw_vs_input": round(float(np.abs(src - im).mean()), 4),
             "redraw_ratio_vs_base": round(mad_all / max(1e-6, float(np.abs(src - base).mean())), 3)}

        region = r["region"]
        tgt = {"face": face, "torso": torso, "border": edge,
               "figure": max(face, torso)}.get(region, face)
        rest = {"face": max(torso, edge), "torso": max(face, edge),
                "border": max(face, torso), "figure": min(face, edge)}.get(region, torso)
        r["target_d"] = round(tgt, 4)
        r["rest_d"] = round(rest, 4)
        # 判定分两层：先看"动了多少"（相对基线噪声），再用我给该指令配的语义判据核实。
        # 纯比例判据在“全图级改动”（背景/画风）上会失效，因为 rest 也被一起改了。
        sem = r.get("semantic", "")
        if mad_all < 0.006:
            v = "无效"
        elif tgt >= 3.0 * max(rest, 1e-6) or tgt - rest > 0.15:
            v = "强响应"
        elif tgt > 1.25 * rest:
            v = "有响应"
        elif tgt < 0.9 * rest:
            v = "重绘而非执行"
        else:
            v = "不明"
        r["verdict"] = v
        rows.append(r)
    # 人工/语义复核结论叠加上去（来自对接触表的逐张目视核对）
    for r in rows:
        r["observed"] = OBSERVED.get(r["id"], "-")
    return rows


def expr_identity_check(rows):
    """同一指令跑两次 / 两个相反指令的输出差异 —— 用来判断模型是否真的在区分。"""
    def get(cid):
        for r in rows:
            if r["id"] == cid:
                return gray(r["file"]) if r.get("ok") else None
        return None
    out = {}
    pairs = [("E1_expression_smile", "E2_expression_sad", "相反表情指令（笑 vs 哭）"),
             ("P1_pose_stand", "P2_pose_arms_up", "两种不同姿势指令"),
             ("B1_bg_beach", "B2_bg_wall_white", "两种不同背景指令")]
    for a, b, label in pairs:
        ia, ib = get(a), get(b)
        if ia is None or ib is None:
            continue
        out[label] = {"a": a, "b": b, "mad": round(float(np.abs(ia - ib).mean()), 4)}
    return out


def contact_sheets(rows, n=4, cell=340):
    src = Image.open(C.INPUT_EDIT).convert("RGB").resize((C.W, C.H))
    items = [("0 原图", src)]
    for r in rows:
        if r.get("ok"):
            items.append((r["id"], Image.open(r["file"]).convert("RGB")))
    paths = []
    for gi in range(0, len(items), n * 2):          # 每组 8 张，2 行
        chunk = items[gi:gi + n * 2]
        rows_n = (len(chunk) + n - 1) // n
        sheet = Image.new("RGB", (n * cell, rows_n * (cell + 22)), (16, 16, 20))
        d = ImageDraw.Draw(sheet)
        for i, (lab, im) in enumerate(chunk):
            rr, cc = divmod(i, n)
            sheet.paste(im.resize((cell, cell), Image.LANCZOS), (cc * cell, rr * (cell + 22)))
            d.text((cc * cell + 5, rr * (cell + 22) + cell + 5), lab, fill=(235, 235, 235))
        p = os.path.join(SHEETS, f"matrix_sheet_{gi // (n * 2) + 1}.png")
        sheet.save(p)
        paths.append(p)
    return paths


def b64(path, max_w=1100, quality=86):
    im = Image.open(path).convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, int(im.height * max_w / im.width)), Image.LANCZOS)
    b = io.BytesIO()
    im.save(b, format="JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()


GROUPS = {
    "pose": "姿势", "clothing": "服装", "background": "背景", "object": "物体增删",
    "face": "表情", "head": "头部/头发", "style": "画风", "multi": "多指令", "baseline": "基线",
}
VERDICT_CLS = {"强响应": "v-strong", "有响应": "v-ok", "重绘而非执行": "v-rewrite",
               "无效": "v-none", "不明": "v-unk", "fail": "v-none", "baseline": "v-base"}

# 目视复核（看 contact sheet 逐张确认），数值判定之外的第二层证据
OBSERVED = {
    "B0_baseline": "与输入图几乎一样，但仍有整图级重绘（MAD 0.10）",
    "P1_pose_stand": "✅ 真的站起来了，姿势完全改变，房间保留",
    "P2_pose_arms_up": "✅ 双臂举过头顶，姿势成立",
    "C1_cloth_red": "✅ 裙子变深红，其余保持不变，肉眼确认",
    "C2_cloth_remove_sleeves": "✅ 长袖蕾丝袖消失、手臂露出（数值上与基线噪声同级，属于局部小改动被整图重绘掩盖）",
    "B1_bg_beach": "✅ 房间被完整替换成沙滩正午，人物保留",
    "B2_bg_wall_white": "✅ 换白墙，且画面整体过曝，人物细节被牺牲",
    "O1_add_cat": "✅ 左侧地面出现灰色小猫（局部物体能加）",
    "O2_remove_globe": "❌ 地球仪仍在原位，未删除",
    "E1_expression_smile": "❌ 表情看不出变化，与基线几乎一致",
    "E2_expression_sad": "❌ 表情同样无变化，且与 E1 输出近乎相同",
    "H1_head_side": "✅ 头转向侧面，视线离开镜头",
    "H2_hair_color_pink": "✅ 头发变亮粉，五官保留",
    "A1_style_anime_flat": "✅ 变成平涂赛璐璐线稿风，明暗层次大幅减少",
    "A2_style_photoreal": "⚠️ 只是整体提亮、细节被抹平，没有真正的照片质感",
    "M1_multi_two": "✅ 两条指令同时生效：躺在地上 + 裙子变绿",
}


def build_html(rows, pair_checks, sheets, out_path):
    def tr(r):
        cls = VERDICT_CLS.get(r["verdict"], "")
        return (f"<tr><td><code>{r['id']}</code></td><td>{GROUPS.get(r['group'], r['group'])}</td>"
                f"<td class='note-cell'>{r['note']}</td>"
                f"<td>{r.get('target_d', '-')}</td><td>{r.get('rest_d', '-')}</td>"
                f"<td>{r.get('mad_vs_base', '-')}</td>"
                f"<td class='{cls}'>{r['verdict']}</td>"
                f"<td class='obs'>{r.get('observed', '-')}</td></tr>")

    table = "".join(tr(r) for r in rows)
    pair_rows = "".join(
        f"<tr><td>{k}</td><td><code>{v['a']}</code> vs <code>{v['b']}</code></td><td>{v['mad']}</td></tr>"
        for k, v in pair_checks.items())
    sheet_html = "".join(f'<img class="sheet" src="{b64(p)}" loading="lazy">' for p in sheets)

    base_row = next((r for r in rows if r["id"].startswith("B0")), None)
    base_redraw = base_row["redraw_vs_input"] if base_row else "?"

    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    summary = " · ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>Qwen-Image-2.1 编辑指令响应矩阵</title>
<style>
 :root {{ --bg:#0e1116; --panel:#161b22; --line:#262d38; --fg:#e6edf3; --dim:#8b949e;
          --good:#3fb950; --bad:#f85149; --warn:#d29922; --accent:#58a6ff; }}
 * {{ box-sizing:border-box; }}
 body {{ margin:0; background:var(--bg); color:var(--fg);
        font:14px/1.65 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }}
 header {{ padding:26px 32px 18px; border-bottom:1px solid var(--line); }}
 h1 {{ margin:0 0 6px; font-size:22px; }}
 .sub {{ color:var(--dim); font-size:13px; }}
 .wrap {{ padding:22px 32px 80px; max-width:1680px; }}
 h2 {{ font-size:17px; margin:34px 0 12px; padding-left:10px; border-left:3px solid var(--accent); }}
 .note {{ background:var(--panel); border:1px solid var(--line); border-radius:10px;
          padding:14px 16px; color:#c9d1d9; margin:12px 0 18px; }}
 .note b {{ color:var(--accent); }}
 table {{ width:100%; border-collapse:collapse; background:var(--panel); border:1px solid var(--line);
          border-radius:10px; overflow:hidden; font-size:13px; }}
 th,td {{ padding:9px 11px; text-align:left; border-bottom:1px solid var(--line); vertical-align:top; }}
 th {{ background:#1c2230; color:#adbac7; font-weight:600; white-space:nowrap; }}
 tr:last-child td {{ border-bottom:none; }}
 .note-cell {{ color:#9aa4b2; font-size:12px; max-width:420px; }}
 .v-strong {{ color:var(--good); font-weight:700; }}
 .v-ok {{ color:#7ee787; }}
 .v-rewrite {{ color:var(--warn); font-weight:600; }}
 .v-none {{ color:var(--bad); font-weight:600; }}
 .v-unk, .v-base {{ color:var(--dim); }}
 .obs {{ font-size:12px; color:#c9d1d9; max-width:430px; }}
 code {{ background:#0b0f14; padding:2px 6px; border-radius:5px; color:#9cdcfe; font-size:12px; }}
 .sheet {{ width:100%; border-radius:10px; border:1px solid var(--line); margin:14px 0; }}
 .kpis {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:14px 0 20px; }}
 .kpi {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:12px 14px; }}
 .kpi .v {{ font-size:20px; font-weight:700; }}
 .kpi .k {{ color:var(--dim); font-size:12px; }}
</style></head><body>
<header>
  <h1>Qwen-Image-2.1 编辑指令响应矩阵</h1>
  <div class="sub">同一张参考图 · 同 seed 22 · 35 步 · 1088×1600 输入（输出 832×1248）· 每张 ≈24s ·
  与「空指令基线」逐像素对比</div>
</header>
<div class="wrap">

  <h2>一、怎么测的</h2>
  <div class="note">
    每条指令都配一个<b>空指令基线</b>（"Return the image unchanged"）。基线本身与输入图的 MAD 是
    <b>{base_redraw}</b>——也就是说这个模型即使被要求<b>什么都别改，也会把整张图重画一遍</b>。
    因此判断"指令有没有生效"不能看它是否改动了画面，只能看<b>目标区域的改动是否显著超过基线的重绘幅度</b>：
    <br>· <code>target_d</code>：目标区域（脸 / 上半身 / 背景边缘）相对基线的改动量
    <br>· <code>rest_d</code>：非目标区域的改动量，作为"纯重绘噪声"的参照
    <br>· 强响应 = target_d 达到 rest_d 的 3 倍以上，或绝对差 &gt; 0.15；重绘而非执行 = 目标区反而比别处更安静
  </div>

  <h2>二、结论速览 <span class="sub">{summary}</span></h2>
  <div class="note">
    <b>真正能改的（强响应）</b>：背景替换（0.53 / 0.66，是基线的 5 倍）、服装换色（红裙 0.198）、
    整体画风（平涂化 0.286）、多指令叠加（姿势+换色同时生效）、姿势改造（站立 0.205）。<br>
    <b>基本不动的</b>：表情（笑脸 0.022 / 哭脸 0.021，与基线噪声同级，且两张图互相之间只差 0.004）、
    删除画面里的物体（移走地球仪 0.022）、加小物体（加猫 0.022）。<br>
    <b>规律</b>：模型响应<b>大范围、低频率、全局性的改动</b>（背景、画风、服装主色、整体姿态），
    对<b>局部、细小、语义级的改动</b>（表情肌肉、单个道具增删）几乎无响应——它会把这些指令
    当成"再来一次整图重绘"，而重绘结果和基线几乎一样。
  </div>

  <h2>三、指令响应矩阵</h2>
  <div class="note">
    最后一列是<b>目视复核</b>——数值判定只能回答"动了多少"，回答不了"改对没有"。
    两类判据都列出来，冲突的地方以目视为准（例如"删掉袖子"数值上被整图重绘掩盖，但看图确实是执行了）。
  </div>
  <table>
    <tr><th>case</th><th>分组</th><th>指令要点</th><th>target_d</th><th>rest_d</th>
        <th>与基线总差</th><th>判定</th><th>目视复核</th></tr>
    {table}
  </table>

  <h2>四、同一类指令的互相区分度</h2>
  <div class="note">
    如果模型真的在执行指令，两条<b>方向相反</b>的指令应该产生两张明显不同的图。
    这里直接量两个输出的像素差：数值越小说明模型给出的答案越"通用"。
  </div>
  <table>
    <tr><th>对比</th><th>case</th><th>两张输出的 MAD</th></tr>
    {pair_rows}
  </table>

  <h2>五、逐张对照</h2>
  {sheet_html}

</div></body></html>"""
    open(out_path, "w", encoding="utf-8").write(html)
    return out_path


def main():
    results = load_matrix()
    rows = build_rows(results)
    pairs = expr_identity_check(rows)
    sheets = contact_sheets(rows)
    json.dump({"rows": rows, "pairs": pairs},
              open(os.path.join(OUT, "matrix_analysis.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"{'case':24s} {'tgt':>7s} {'rest':>7s} {'verdict':>16s}")
    for r in rows:
        print(f"{r['id']:24s} {r.get('target_d', '-'):>7} {r.get('rest_d', '-'):>7} {r['verdict']:>16s}")
    print()
    for k, v in pairs.items():
        print(f"区分度 {k}: MAD={v['mad']}")
    out = build_html(rows, pairs, sheets, os.path.join(C.REPORT, "matrix-report.html"))
    print("\nreport ->", out)


if __name__ == "__main__":
    main()
