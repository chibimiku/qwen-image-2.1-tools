# -*- coding: utf-8 -*-
"""生成最终的故事长页 HTML：文字 + 每张图的**完整路径**（不嵌入图片）。

  python exp/galgame-cg-20260928/build_gallery.py
  → exp/galgame-cg-20260928/gallery.html

## 为什么图片不嵌进 HTML

需求明确：**图不要直接嵌入 HTML**，只给完整路径，便于自己修复替换。
所以页面上每张图给三样东西：
  1. 可复制的**完整绝对路径**（直接粘进任何工具里用）
  2. 相对路径（便于从仓库根目录引用）
  3. 一个「打开图片」按钮（用 file:// 打开本机文件）

## 数据来源

每张 CG 的状态、选用版本、prompt 都写在下面的 `SCENES` 里，
改图之后只改这里、重跑本脚本即可，不用手改 HTML。
"""
from __future__ import annotations

import argparse
import html
import json
import pathlib
import sys

EXP = pathlib.Path(__file__).resolve().parent
REPO = EXP.parents[1]

# --------------------------------------------------------------------------- #
# 分幕数据
#   img    相对于仓库根的路径（用 / 分隔）
#   use    选用哪一版 / 状态
#   note   这版为什么选它（或还差什么）
#   kind   ok | edited | regen | fixed | todo
# --------------------------------------------------------------------------- #
SCENES: list[dict] = [
    {
        "no": "01", "title": "进店", "act": "第一幕 · 量",
        "role": "堇 + 里屋的暖暖（只见裙）",
        "text": [
            "约的是四点。她比我早到，门已经开了。里屋有人在哼歌。",
            "旧街二楼的木楼梯尽头，她站在门里侧，手还搭在门把上——"
            "她没有先说话，先看的是我的肩。",
        ],
        "line": "堇：「……约的是四点吧？先进来，别站在楼梯口。」",
        "img": "exp/galgame-cg-20260928/story/01-entrance.png",
        "use": "出图版", "kind": "ok",
        "note": "门框、衣架、**里屋那件粉裙的钩子**都在（她是主角，但第一眼先给钩子）。",
    },
    {
        "no": "02", "title": "量肩", "act": "第一幕 · 量",
        "role": "堇 + 你（客人的肩在右侧虚焦出画）",
        "text": [
            "她绕到我身后，布尺从肩上过去。她的手很稳，眼神只在肩线上——"
            "不看人。",
            "然后停了一下。很短，短到可以当成是她在读数。",
        ],
        "line": "堇：「你抬手，我看看肩线。」",
        "img": "exp/galgame-cg-20260928/story/02-measure.png",
        "use": "出图版", "kind": "ok", "best": True,
        "note": "全篇最好的一张。**改成单人视角才成立**：客人只出现肩与后颈、还虚焦，"
                "主体是她的手与布尺。第一版要求「两人都在画面里」，模型给同一个人画了两个副本。"
                "另：客人没画上衣，按确认保留原样。",
    },
    {
        "no": "03", "title": "那件事", "act": "第一幕 · 量",
        "role": "堇 + 你",
        "text": ["她放下尺，笔尖停在记事本上。", "她的表情没有变，但眼睛变了一瞬。"],
        "line": "堇：「那个人，是什么样的？」",
        "extra": "隔壁试衣区的帘子后面传来暖暖的声音：「堇姐！这条裙长你是不是又给我改短了——」",
        "img": "exp/galgame-cg-20260928/story/03-the-question.png",
        "use": "出图版", "kind": "ok",
        "note": "抬眼 + 笔停在记事本上的动作都对。",
    },
    {
        "no": "04", "title": "换衣", "act": "第一幕 · 量",
        "role": "堇 + 你",
        "text": [
            "她替我把衬衫最上面那颗扣子解开。指尖停在第二颗上，没有往下。",
            "她抬眼看我。离得很近。",
        ],
        "line": "堇：「……肩线没问题了。」（她答的是上一个问题）",
        "img": "exp/galgame-cg-20260928/story/04-unbutton.png",
        "use": "⚠️ 待换模型", "kind": "todo",
        "note": "**本机做不到这一幕。** 唯一内容是「她的手停在另一个人的衬衫上」，"
                "即「与另一个人发生的动作」：出图画成她在扣自己的衬衫并对镜头笑；"
                "后期 edit 也完全没改成功。详见 STORY-GEN-REPORT.md 第四节，"
                "那里写了换模型时要验的三件事与两个备选构图。",
    },
    {
        "no": "05", "title": "咖啡厅", "act": "第二幕 · 试",
        "role": "堇 + 你",
        "text": [
            "窗边小圆桌。她双手捧着冰茶杯，斜前方放着一块草莓蛋糕。",
            "她手机亮了一下，她看了一眼，没回。",
        ],
        "line": "堇：「她挑料子的话……大概会选缎面。我先问问。」",
        "img": "exp/galgame-cg-20260928/fixed-2/story-02-cafe.png",
        "use": "修复版", "kind": "fixed",
        "note": "用修复版（首版只画了单手，要求「双手捧杯」）。场上还没出现第二个人，"
                "但台词已经在替她准备。",
    },
    {
        "no": "06", "title": "街上", "act": "第二幕 · 试",
        "role": "堇 + 你",
        "text": ["沿街走。她拎着纸袋，回头看我，嘴角有一点笑。", "她自己大概没意识到。"],
        "line": "",
        "img": "exp/galgame-cg-20260928/fixed-2/story-03-street.png",
        "use": "修复版", "kind": "fixed",
        "note": "用修复版（首版四指与提绳焊在一起、鞋跟成玻璃块）。",
    },
    {
        "no": "07a", "title": "冰淇淋", "act": "第二幕 · 试 · 分支（轻松线）",
        "role": "堇 + 你",
        "text": ["海港步道。她一手甜筒、一手纸巾，风把头发吹起来。",
                 "太阳低下去的时候，她忽然不说话了。"],
        "line": "",
        "img": "exp/galgame-cg-20260928/story/07a-icecream.png",
        "use": "重出版", "kind": "regen",
        "note": "**重出**（不是 edit）。真正的黄金时刻：太阳低垂、海面拖出长条金色反光、"
                "投影朝镜头拉长。旧版是正午强光，与「午后咖啡厅」之后不连续。"
                "⚠️ 不要用同名的 edit 版（它没做出黄金时刻，还把整张重画了）。",
    },
    {
        "no": "07b", "title": "两个人的量体", "act": "第二幕 · 试 · 分支（紧张线）",
        "role": "**堇 + 暖暖（唯一一次两人同框）**",
        "text": [
            "回工作室。暖暖已经在里面等着了，见我进来也不避，"
            "「你就是堇姐说的那个人？」，说完自己先笑了。",
            "堇替她张开手臂量体。我在旁边看着——两个人各自为了同一个人认真准备。",
            "**而我全程知道，她们俩都不知道。**",
        ],
        "line": "堇：「抬手。……你这个肩，比上次量的时候窄了。」"
                "　暖暖：「哪有。是你尺子拿歪了。」（说完去摸裙摆上那行字）",
        "line2": "堇：「……你今天，是要去见谁？」（她问的时候，没看暖暖）",
        "img": "exp/galgame-cg-20260928/story/07b-three-fitting.png",
        "use": "出图版", "kind": "ok", "key": True,
        "note": "**全篇最酸的一场，也是唯一证实「两个角色能同框而不串味」的一张。** "
                "第一版画成两组人 + 地板整块星座连线；改成把「不要」写成「要什么」"
                "（正面描述背景）+ 把不重复禁在画法层之后成立。蓝发与粉发一眼分得开。",
    },
    {
        "no": "08", "title": "长凳", "act": "第二幕 · 试",
        "role": "堇 + 你（暖暖已走）",
        "text": ["秋日公园。她坐在长凳上，腿垂在凳前，抬头看落下的叶子。",
                 "她手里还握着半卷布尺——暖暖那件剩下的。"],
        "line": "",
        "img": "exp/galgame-cg-20260928/fixed-2/story-05-park.png",
        "use": "修复版", "kind": "fixed",
        "note": "用修复版（首版臀腿悬在座面前方，承重关系不成立）。",
    },
    {
        "no": "09", "title": "落日桥", "act": "第二幕 · 试 · 转折",
        "role": "堇 + 你",
        "text": ["她靠在桥栏上看河面。说完那句话之后，侧脸没有转回来。"],
        "line": "堇：「这套……我给自己也留了一件。」",
        "extra": "她说的是暖暖那件。她说的是同一个人。",
        "img": "exp/galgame-cg-20260928/fixed-2/story-06-sunset-bridge.png",
        "use": "修复版", "kind": "fixed",
        "note": "用修复版（首版是 P0：同一个人被画了两次）。",
    },
    {
        "no": "10a", "title": "顺着问下去", "act": "第三幕 · 说 · 分支",
        "role": "堇（你不在画面里）",
        "text": [
            "夜里只剩一盏台灯。她背对着我，一侧背带滑下肩，手停在腰上第二颗金扣上。",
            "工作台上摊着暖暖那件格纹裙——同一张桌子上，两份「准备」并排。",
            "她没有回头。",
        ],
        "line": "堇：「你过来。……这边，要量一下。」",
        "img": "exp/galgame-cg-20260928/story-edited/10a-unhook.png",
        "use": "edit 版", "kind": "edited",
        "note": "服装状态、扣环、台灯、开衫、粉裙都对；edit 只把表情从甜笑改得稍微收敛"
                "（仍有笑）。**她把自己交出去的姿势，仍然是工作的姿势。**",
    },
    {
        "no": "10b", "title": "装没听见", "act": "第三幕 · 说 · 分支（备选）",
        "role": "堇",
        "text": ["她背对我收拾衣架，台灯只照亮半间屋子。",
                 "暖暖那件裙已经叠好，压着一张写着地址的便签。"],
        "line": "",
        "img": "",
        "use": "未出图（分支备选）", "kind": "todo",
        "note": "如果只做单线，这一幕不需要；10a 已经承担了同样的转折。",
    },
    {
        "no": "11", "title": "试衣镜前", "act": "第三幕 · 说（成人场景 · 主拍）",
        "role": "堇",
        "text": [
            "她背靠着落地镜，两条背带都滑到肘上。一只手撑在镜面上，"
            "另一只手还捏着那根布尺，尺子垂下来搭在大腿上。",
            "她看的是镜中的我，不是她自己。",
            "**她抓着的还是那根量尺——那是她唯一的遮挡物。**",
        ],
        "line": "堇：「……你再近一点，我就量不准了。」",
        "img": "exp/galgame-cg-20260928/story-edited/11-mirror-adult.png",
        "use": "edit 版", "kind": "edited", "key": True,
        "note": "出图阶段被模型「净化」（衬衫没敞开、裙长变短），"
                "**后期 edit 把三项都改到了**，背带滑落／手撑镜面／垂下的布尺原样保住。"
                "代价：裙摆的「天蓝→薄荷绿」渐变被吃掉（keep 列表里漏了配色）。",
    },
    {
        "no": "12", "title": "近景", "act": "第三幕 · 说",
        "role": "堇",
        "text": ["她看着我，笑里带一点紧张。领口还没扣好。",
                 "她问的时候，我手机在震——是暖暖发来的：「堇姐我明天几点来试？」"],
        "line": "堇：「所以……今天这套，是穿给我看的吗？」",
        "img": "exp/galgame-cg-20260928/story-edited/12-closeup.png",
        "use": "edit 版", "kind": "edited",
        "note": "剧本要求「领口未扣好 + 锁骨上一道浅印」——身体已经答过了，她却偏要再听一次。"
                "edit 做到了，表情还自动变成带一点紧张的浅笑。",
    },
    {
        "no": "13a", "title": "直接说出来", "act": "第三幕 · 说 · 分支（结局 A）",
        "role": "堇 + 你",
        "text": ["路灯下，她双手提着小购物袋，一只脚内撇。", "她说完自己愣了一下。"],
        "line": "堇：「那你早说啊，我量了半天。」（说完自己笑了）",
        "line2": "堇：「……那明天，让她别来了。」",
        "img": "exp/galgame-cg-20260928/story-edited/13a-goodnight.png",
        "use": "重出 + 再修", "kind": "regen", "key": True,
        "note": "重出把夜压对了（灯下一小片暖光池、更深更饱和），但脸沉在阴影里；"
                "三个 seed 都改不掉（模型配光的稳定倾向），于是做了一次**局部光照**的 edit "
                "把脸抬出来——**没有重画**，路灯/袋子/姿势/服装全保留。",
    },
    {
        "no": "13b", "title": "把邀约放进衣服里", "act": "第三幕 · 说 · 分支（结局 B）",
        "role": "无人物",
        "text": ["第二天早上，工作台上摊着**两件**刚改好的衣服——"
                 "一件是我的衬衫，一件是暖暖那件格纹裙。",
                 "两件胸口各别着一张手写便签。**不用她当场回答，信是给人留时间的。**"],
        "line": "",
        "img": "exp/galgame-cg-20260928/story/13b-note.png",
        "use": "出图版", "kind": "ok",
        "note": "静态物构图，本机的强项区。是**编辑推荐**的结局。",
    },
    {
        "no": "14", "title": "信", "act": "尾声 · 全篇落点",
        "role": "无人物",
        "text": [
            "工作室的木桌上，一张摊开的信纸，和一小截用剩的布尺。",
            "桌角还压着暖暖那件裙子的下摆——**「POETRY BLOOM」那行字正好从纸边露出来**。",
            "她替别人挑了那么多年，第一次有人替她把这一天挑好。",
        ],
        "line": "",
        "img": "exp/galgame-cg-20260928/story/14-letter.png",
        "use": "出图版", "kind": "ok", "key": True,
        "note": "**全篇唯一让「两件衣服同框」的镜头。** 她替暖暖做的、她替自己留的，"
                "最后并排躺在同一张桌上。不用写一句话解释。",
    },
]

KIND_LABEL = {
    "ok":     ("出图即成立", "k-ok"),
    "edited": ("后期 edit 修成", "k-edit"),
    "regen":  ("重出（回到出图阶段）", "k-regen"),
    "fixed":  ("用早先的修复版", "k-fix"),
    "todo":   ("待处理", "k-todo"),
}

CSS = """
:root{
  --bg:#14141a; --panel:#1c1c24; --panel2:#22222c; --line:#33333f;
  --fg:#e8e8ee; --dim:#9a9aa8; --warm:#e8c07a; --blue:#8fb8e8;
  --pink:#e8a8c0; --ok:#8fd0a0; --warn:#e8b06a; --bad:#e88a8a;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font:15px/1.85 "Microsoft YaHei","PingFang SC",system-ui,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:44px 26px 90px}
h1{font-size:30px;margin:0 0 6px;letter-spacing:.02em}
h2{font-size:19px;margin:52px 0 16px;padding-bottom:9px;border-bottom:1px solid var(--line);
  color:var(--warm)}
.sub{color:var(--dim);font-size:14px;margin:0 0 6px}
.meta{color:var(--dim);font-size:13.5px}
.meta b{color:var(--fg);font-weight:600}
hr.sep{border:0;border-top:1px solid var(--line);margin:46px 0}
.act{font-size:13px;letter-spacing:.16em;color:var(--warm);margin:44px 0 4px}
.scene{background:var(--panel);border:1px solid var(--line);border-radius:11px;
  padding:20px 22px 18px;margin:16px 0}
.scene.key{border-color:#4a4436;background:linear-gradient(180deg,#20201a,#1c1c24)}
.sno{display:inline-block;min-width:52px;font-weight:700;color:var(--blue);
  font-size:17px;letter-spacing:.03em}
.stitle{font-size:19px;font-weight:700}
.role{color:var(--dim);font-size:13px;margin-top:3px}
.text{margin:14px 0 0}
.line{margin:14px 0 0;padding:11px 15px;border-left:3px solid var(--warm);
  background:#201f26;border-radius:0 7px 7px 0;color:#f3e7cf}
.line + .line{margin-top:8px}
.extra{margin:12px 0 0;color:var(--dim);font-size:14px;font-style:italic}
.tag{display:inline-block;font-size:12px;padding:2px 9px;border-radius:20px;
  margin-left:8px;vertical-align:middle;font-weight:600}
.k-ok{background:#1e3326;color:var(--ok);border:1px solid #2e4d3a}
.k-edit{background:#2c2a1e;color:var(--warn);border:1px solid #4a4327}
.k-regen{background:#1e2c38;color:var(--blue);border:1px solid #2b4054}
.k-fix{background:#262230;color:#b8a8e0;border:1px solid #3a3350}
.k-todo{background:#34211f;color:var(--bad);border:1px solid #55322e}
.imgbox{margin:16px 0 0;background:var(--panel2);border:1px solid var(--line);
  border-radius:9px;padding:14px 16px}
.pathrow{display:flex;align-items:center;gap:9px;flex-wrap:wrap}
.pathrow code{flex:1;min-width:280px;background:#15151b;border:1px solid var(--line);
  border-radius:6px;padding:8px 11px;font:12.5px/1.5 Consolas,"Courier New",monospace;
  color:#cfe0ff;overflow-wrap:anywhere}
button{background:#2a2a36;color:var(--fg);border:1px solid var(--line);border-radius:6px;
  padding:7px 12px;font-size:12.5px;cursor:pointer;font-family:inherit;white-space:nowrap}
button:hover{background:#35354a;border-color:#4a4a60}
.hint{color:var(--dim);font-size:12.5px;margin-top:7px}
.note{margin:13px 0 0;color:#c8c8d4;font-size:14px}
.note b{color:var(--fg)}
table{width:100%;border-collapse:collapse;margin-top:12px;font-size:13.5px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}
th{color:var(--warm);font-weight:600;font-size:13px}
td.n{color:var(--blue);font-weight:700;white-space:nowrap}
.warn{background:#241a1a;border:1px solid #5a3230;border-radius:9px;padding:15px 18px;
  margin:22px 0}
.warn b{color:var(--bad)}
.stat{display:flex;gap:26px;flex-wrap:wrap;margin:16px 0 0}
.stat div{color:var(--dim);font-size:13.5px}
.stat span{color:var(--fg);font-weight:700;font-size:17px;margin-right:5px}
.copyok{color:var(--ok);font-size:12.5px}
"""

JS = """
function cp(btn){
  const code = btn.parentElement.querySelector('code');
  const t = code.textContent.trim();
  const done = () => { const s=btn.textContent; btn.textContent='已复制';
    btn.classList.add('copyok');
    setTimeout(()=>{btn.textContent=s; btn.classList.remove('copyok');},1300); };
  if (navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(t).then(done).catch(()=>{fallback(t,done);});
  } else { fallback(t,done); }
}
function fallback(t,done){
  const ta=document.createElement('textarea'); ta.value=t;
  ta.style.position='fixed'; ta.style.opacity='0';
  document.body.appendChild(ta); ta.select();
  try{ document.execCommand('copy'); done(); }catch(e){ alert('复制失败，请手动选择路径'); }
  document.body.removeChild(ta);
}
function openImg(btn){
  // 「复制路径」那条是 Windows 绝对路径（带反斜杠），粘进本机工具用。
  // 浏览器不能直接开 file:///（会被拦），所以把同一个路径转成 URL 形式。
  // 注意：不能整段 encodeURIComponent —— 它会把盘符的冒号也编成 %3A，
  // 那样 file:// 就失效了；只对每一段路径做编码（空格 → %20）。
  const code = btn.parentElement.querySelector('code');
  const win = code.textContent.trim().replace(/\\\\/g, '/');
  const parts = win.split('/');
  const head = parts.shift();                      // 'C:' 之类，保持原样
  window.open('file:///' + head + '/' + parts.map(encodeURIComponent).join('/'), '_blank');
}
"""


def abspath(rel: str) -> str:
    return str((REPO / rel).resolve())


def render() -> str:
    out: list[str] = []
    n_ok = sum(1 for s in SCENES if s["kind"] in ("ok", "fixed"))
    n_edit = sum(1 for s in SCENES if s["kind"] == "edited")
    n_regen = sum(1 for s in SCENES if s["kind"] == "regen")
    n_todo = sum(1 for s in SCENES if s["kind"] == "todo")

    out.append("<!doctype html>")
    out.append('<html lang="zh-CN"><head><meta charset="utf-8">')
    out.append('<meta name="viewport" content="width=device-width,initial-scale=1">')
    out.append("<title>《量尺另一端》— 故事 CG 长页</title>")
    out.append(f"<style>{CSS}</style></head><body><div class='wrap'>")

    out.append("<h1>《量尺另一端》</h1>")
    out.append("<p class='sub'>Styling for Someone Else · 短篇 galgame CG 故事（R18）</p>")
    out.append("<p class='meta'>文字 + 图路径。图片<strong>不嵌入本页</strong>，"
               "每张下面给的是可直接复制的完整路径与一个「打开图片」按钮，"
               "便于你定位、修复、替换。</p>")

    out.append("<div class='stat'>")
    out.append(f"<div><span>{n_ok}</span>出图即成立</div>")
    out.append(f"<div><span>{n_edit}</span>后期 edit 修成</div>")
    out.append(f"<div><span>{n_regen}</span>重出</div>")
    out.append(f"<div><span>{n_todo}</span>待处理</div>")
    out.append(f"<div><span>{len(SCENES)}</span>分幕总数</div>")
    out.append("</div>")

    # ── 故事核 ──
    out.append("<h2>故事核</h2>")
    out.append("<p>你是那个「替别人准备重要一天」的人。她替无数人挑好赴约的衣服，"
               "却从来没人替她挑过一次。</p>")
    out.append("<p>而今天，全世界只有她还不知道——"
               "<strong>那个「别人」就是她自己</strong>。</p>")
    out.append("<p class='meta'>两条准备线并行：<b>堇</b>（搭配师）替你准备；"
               "<b>暖暖</b>（老客）让堇替她准备。<b>两个人要见的是同一个人。</b>"
               "玩家全程知道，两个角色各自不知道——信息差就是全篇的张力来源，"
               "所以高潮不是告白，是<strong>两个人终于对上账</strong>的那一刻。</p>")

    # ── 三个主角 ──
    out.append("<h2>角色</h2>")
    out.append("<table><tr><th>角色</th><th>视觉</th><th>在这个故事里</th></tr>")
    out.append("<tr><td class='n'>堇</td>"
               "<td>靛蓝色及肩波浪发、一侧小丸子、白色小花发饰、蓝紫眼；"
               "白泡泡袖衬衫 + 蓝色牛仔背带裙（裙摆天蓝→薄荷绿渐变）；"
               "蓝色蝴蝶结玛丽珍高跟</td>"
               "<td>搭配师，小工作室在旧街二楼。慢热、克制，把关心放在细节里。"
               "口头禅「你抬手，我看看肩线」既是职业台词，也是她挡住情绪的方式</td></tr>")
    out.append("<tr><td class='n'>暖暖</td>"
               "<td>浅粉色及腰直发、发尾微卷、暖棕眼；白色罗纹针织毛衣 + "
               "淡粉格纹背带裙，胸口红丝带；"
               "<strong>裙摆一圈印着 POETRY BLOOM</strong></td>"
               "<td>老客。三年前第一次进门就让堇改了裙长，从此只找堇做衣服。"
               "叫堇「堇姐」。紧张时会去摸裙摆上那行字</td></tr>")
    out.append("<tr><td class='n'>你</td><td>不出现</td>"
               "<td>由玩家扮演。全程知道两条线要见的是同一个人</td></tr>")
    out.append("</table>")

    # ── 分幕 ──
    out.append("<h2>分幕</h2>")
    cur_act = None
    for s in SCENES:
        if s["act"] != cur_act:
            cur_act = s["act"]
            out.append(f"<div class='act'>{html.escape(cur_act)}</div>")
        label, cls = KIND_LABEL[s["kind"]]
        keycls = " key" if s.get("key") else ""
        out.append(f"<div class='scene{keycls}'>")
        out.append(f"<div><span class='sno'>{html.escape(s['no'])}</span>"
                   f"<span class='stitle'>{html.escape(s['title'])}</span>"
                   f"<span class='tag {cls}'>{html.escape(s['use'])}</span></div>")
        out.append(f"<div class='role'>人物：{_md(s['role'])}</div>")
        for t in s["text"]:
            out.append(f"<p class='text'>{_md(t)}</p>")
        if s.get("line"):
            out.append(f"<div class='line'>{_md(s['line'])}</div>")
        if s.get("line2"):
            out.append(f"<div class='line'>{_md(s['line2'])}</div>")
        if s.get("extra"):
            out.append(f"<div class='extra'>{_md(s['extra'])}</div>")

        # 图路径
        if s["img"]:
            ap = abspath(s["img"])
            out.append("<div class='imgbox'>")
            out.append("<div class='pathrow'><code>" + html.escape(ap) + "</code>"
                       "<button onclick='cp(this)'>复制路径</button>"
                       "<button onclick='openImg(this)'>打开图片</button></div>")
            out.append(f"<div class='hint'>相对仓库根：<code style='background:none;"
                       f"border:0;padding:0'>{html.escape(s['img'])}</code></div>")
            # 站点内 URL（图拷进 IIS 之后可用；路径含空格所以做了 URL 编码）
            out.append(f"<div class='hint'>网页地址：<code style='background:none;"
                       f"border:0;padding:0'>{html.escape(_site_url(s))}</code></div>")
            out.append(f"<div class='hint'>状态：{label}</div>")
            out.append("</div>")
        else:
            out.append("<div class='imgbox'><div class='hint'>"
                       "（这一幕还没有图 — 见下方说明）</div></div>")

        out.append(f"<p class='note'>{_md(s['note'])}</p>")
        out.append("</div>")

    return "\n".join(out) + "</div><script>" + JS + "</script></body></html>"


def _md(t: str) -> str:
    """只支持 **粗体**（足够表达重点，避免引第三方 md 库）。"""
    t = html.escape(t)
    import re
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)


# --------------------------------------------------------------------------- #
# 发布到 IIS
#
# 站点根：C:\Users\ashsu\Documents\black（web.config 里开了目录浏览）
# 发布到它下面的 gallery\ 子目录，**图一起拷进去**，这样浏览器里直接能看；
# 同时保留本机绝对路径，粘到资源管理器/工具里仍能用。
#
# 为什么要两种路径：路径里有空格与中文，直接拼 URL 会失效。
# 所以给「打开」用的那一条做 URL 编码（空格 → %20），
# 而「复制」用的那一条保持原始形态（粘进本机工具要用原始的）。
# --------------------------------------------------------------------------- #
PUBLISH_SUBDIR = "gallery"
IIS_ROOT = pathlib.Path(r"C:\Users\ashsu\Documents\black")


def _site_url(s: dict) -> str:
    """发布后在站点里的相对 URL。

    发布时把图**按分幕号重命名**（story/01-entrance.png → 01.png），
    因为不同目录下有同名文件（story-edited/10a-unhook.png 与 story/10a-unhook.png），
    按分幕号命名后 URL 干净、也不会互相覆盖。
    分幕号里的字母统一小写（10A → 10a）。
    """
    if not s.get("img"):
        return ""
    no = s["no"].lower()
    return f"{PUBLISH_SUBDIR}/{no}.png"


def publish() -> int:
    """把 gallery.html 与用到的图拷进 IIS 站点，图按分幕号重命名。"""
    import shutil

    dst_dir = IIS_ROOT / PUBLISH_SUBDIR
    if not IIS_ROOT.exists():
        print(f"!! 站点根不存在：{IIS_ROOT}")
        return 2
    dst_dir.mkdir(parents=True, exist_ok=True)

    print(f"发布到 {dst_dir}")
    copied = skipped = 0
    for s in SCENES:
        if not s.get("img"):
            continue
        src = REPO / s["img"]
        if not src.exists():
            print(f"  缺图 {s['no']}: {s['img']}")
            continue
        dst = dst_dir / f"{s['no'].lower()}.png"
        if dst.exists() and dst.stat().st_size == src.stat().st_size:
            skipped += 1
            continue
        shutil.copy2(src, dst)
        copied += 1
    print(f"  图：拷贝 {copied} / 已是最新 {skipped}")

    html_dst = dst_dir / "index.html"
    html_src = EXP / "gallery.html"
    shutil.copy2(html_src, html_dst)
    print(f"  页面：{html_dst.name}  ({html_dst.stat().st_size} 字节)")
    print(f"\n  浏览地址： http://localhost/{PUBLISH_SUBDIR}/")
    print(f"  （站点根开了目录浏览，也可以访问 http://localhost/{PUBLISH_SUBDIR}/ 看文件列表）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--publish", action="store_true", help="生成后拷进 IIS 站点")
    a = ap.parse_args()

    p = EXP / "gallery.html"
    p.write_text(render(), encoding="utf-8")
    print(f"写出 {p}  ({p.stat().st_size} 字节)")
    print(f"  分幕 {len(SCENES)} 条，其中有图的 "
          f"{sum(1 for s in SCENES if s['img'])} 条")
    # 顺手核对每张图是否真的存在
    miss = [s["no"] for s in SCENES
            if s["img"] and not (REPO / s["img"]).exists()]
    if miss:
        print("  ⚠️ 以下分幕的图不存在：", ", ".join(miss))
    else:
        print("  所有引用的图都在磁盘上")

    if a.publish:
        print()
        return publish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
