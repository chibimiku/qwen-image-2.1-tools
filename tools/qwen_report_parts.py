"""HTML builders for the Qwen-Image-2.1 edit-chain report (kept separate for clarity)."""

CSS = """
 :root { --bg:#0e1116; --panel:#161b22; --line:#262d38; --fg:#e6edf3; --dim:#8b949e;
         --good:#3fb950; --bad:#f85149; --accent:#58a6ff; }
 * { box-sizing:border-box; }
 body { margin:0; background:var(--bg); color:var(--fg);
        font:14px/1.6 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }
 header { padding:28px 32px 18px; border-bottom:1px solid var(--line); }
 h1 { margin:0 0 6px; font-size:22px; letter-spacing:.2px; }
 .sub { color:var(--dim); font-size:13px; }
 .wrap { padding:24px 32px 80px; max-width:1600px; }
 h2 { font-size:17px; margin:38px 0 12px; padding-left:10px; border-left:3px solid var(--accent); }
 .note { background:var(--panel); border:1px solid var(--line); border-radius:10px;
         padding:14px 16px; color:#c9d1d9; margin:12px 0 20px; }
 .note b { color:var(--accent); }
 table { width:100%; border-collapse:collapse; background:var(--panel);
         border:1px solid var(--line); border-radius:10px; overflow:hidden; font-size:13px; }
 th,td { padding:9px 12px; text-align:left; border-bottom:1px solid var(--line); }
 th { background:#1c2230; color:#adbac7; font-weight:600; }
 tr:last-child td { border-bottom:none; }
 td.good { color:var(--good); font-weight:600; }
 td.bad { color:var(--bad); font-weight:600; }
 .card { background:var(--panel); border:1px solid var(--line); border-radius:12px;
         padding:14px; margin:16px 0; }
 .card .head { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:10px; }
 .tag { font-weight:700; color:#fff; }
 .conf { color:var(--dim); font-size:12px; }
 .tri { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }
 figure { margin:0; }
 figure img { width:100%; border-radius:8px; display:block; border:1px solid var(--line); }
 figcaption { color:var(--dim); font-size:12px; padding-top:6px; }
 .prompt { color:#9aa4b2; font-size:12px; margin:10px 0 0; border-top:1px dashed var(--line); padding-top:8px; }
 .badge { display:inline-block; padding:2px 8px; border-radius:20px; font-size:11px;
          background:#1f6feb22; color:var(--accent); border:1px solid #1f6feb55; margin-left:8px; }
 .badge.warn { background:#f8514922; color:var(--bad); border-color:#f8514955; }
 .tools { display:grid; grid-template-columns:1fr 1fr; gap:18px; align-items:start; }
 .panel { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px; }
 #cv { width:100%; max-width:520px; border-radius:8px; display:block; cursor:crosshair;
       border:1px solid var(--line); touch-action:none; }
 .row { display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-top:10px; font-size:13px; }
 button { background:#1f6feb; color:#fff; border:0; border-radius:8px; padding:8px 14px;
          font-size:13px; cursor:pointer; }
 button.ghost { background:#21262d; border:1px solid var(--line); color:var(--fg); }
 button:hover { filter:brightness(1.1); }
 input[type=range] { width:150px; }
 code { background:#0b0f14; padding:2px 6px; border-radius:5px; color:#9cdcfe; font-size:12px; }
 .kbd { color:var(--dim); font-size:12px; }
"""

JS_WIDGET = r"""
<script>
const SRC = new Image(), ED = new Image(), BASE = new Image(), OUT_IMG = new Image();
let box = {x:0,y:0,w:0,h:0}, feather = 0.16, scale = 1, drag = null;

function fitCanvas() {
  const cv = document.getElementById('cv');
  cv.width = SRC.naturalWidth; cv.height = SRC.naturalHeight;
  const maxCss = 520;
  scale = Math.min(1, maxCss / cv.width);
  cv.style.width = (cv.width * scale) + 'px';
  redraw();
}

function redraw() {
  const cv = document.getElementById('cv'), g = cv.getContext('2d');
  g.clearRect(0, 0, cv.width, cv.height);
  g.drawImage(ED, 0, 0);
  // 源图人脸区域提示
  g.save();
  g.strokeStyle = 'rgba(88,166,255,.9)'; g.lineWidth = 3; g.setLineDash([8, 6]);
  g.strokeRect(box.x, box.y, box.w, box.h);
  g.restore();
  compose();
}

function compose() {
  const out = document.getElementById('out');
  const g = out.getContext('2d');
  out.width = SRC.naturalWidth; out.height = SRC.naturalHeight;
  g.drawImage(ED, 0, 0);
  if (box.w > 8 && box.h > 8) {
    const m = document.createElement('canvas');
    m.width = box.w; m.height = box.h;
    const mg = m.getContext('2d');
    const blur = Math.max(2, Math.min(box.w, box.h) * feather);
    mg.filter = `blur(${blur / 2}px)`;
    mg.fillStyle = '#000';
    mg.beginPath();
    mg.ellipse(box.w / 2, box.h * 0.52, box.w * 0.47, box.h * 0.50, 0, 0, Math.PI * 2);
    mg.fill();
    mg.filter = 'none';
    // 用 alpha 蒙版把源图人脸贴上去
    const tmp = document.createElement('canvas');
    tmp.width = box.w; tmp.height = box.h;
    const tg = tmp.getContext('2d');
    tg.drawImage(SRC, box.x, box.y, box.w, box.h, 0, 0, box.w, box.h);
    tg.globalCompositeOperation = 'destination-in';
    tg.drawImage(m, 0, 0);
    g.drawImage(tmp, box.x, box.y);
  }
  const o = document.getElementById('out').style;
  o.width = (out.width * scale) + 'px';
}

function pos(ev) {
  const cv = document.getElementById('cv');
  const r = cv.getBoundingClientRect();
  return { x: (ev.clientX - r.left) / (r.width / cv.width),
           y: (ev.clientY - r.top) / (r.height / cv.height) };
}

function init() {
  const cv = document.getElementById('cv');
  cv.addEventListener('pointerdown', e => { drag = pos(e); cv.setPointerCapture(e.pointerId); });
  cv.addEventListener('pointermove', e => {
    if (!drag) return;
    const p = pos(e);
    box = { x: Math.round(Math.min(drag.x, p.x)), y: Math.round(Math.min(drag.y, p.y)),
            w: Math.round(Math.abs(p.x - drag.x)), h: Math.round(Math.abs(p.y - drag.y)) };
    redraw();
  });
  cv.addEventListener('pointerup', () => { drag = null; updateHash(); });
  document.getElementById('feather').addEventListener('input', e => {
    feather = parseFloat(e.target.value); compose();
  });
  document.getElementById('reset').addEventListener('click', () => {
    box = { x: DEFAULT_BOX[0], y: DEFAULT_BOX[1], w: DEFAULT_BOX[2], h: DEFAULT_BOX[3] };
    redraw(); updateHash();
  });
  document.getElementById('save').addEventListener('click', () => {
    const a = document.createElement('a');
    a.download = 'facefix_manual.png';
    a.href = document.getElementById('out').toDataURL('image/png');
    a.click();
  });
}

function updateHash() {
  const h = `#box=${box.x},${box.y},${box.w},${box.h}`;
  history.replaceState(null, '', h);
  document.getElementById('boxinfo').textContent =
    `box = ${box.x},${box.y},${box.w},${box.h}   feather = ${feather}`;
}

function start() {
  SRC.onload = () => { ED.onload = () => { fitCanvas(); updateHash(); }; ED.src = EDITED_URL; };
  SRC.src = SOURCE_URL;
  init();
}
</script>
"""
