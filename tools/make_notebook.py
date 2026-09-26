#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成 JupyterLab 用的控制台笔记本（service/ui/Qwen-Image-2.1-控制台.ipynb）。

需要改内容时改这个脚本再重跑，不要直接编辑 .ipynb（JSON 手改容易崩）。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "service", "ui", "Qwen-Image-2.1-console.ipynb")

# ── 笔记本里反复用到的公共代码 ──────────────────────────────────────────────
KEY_HELPER = '''import getpass

def read_key():
    """要调服务就得有 key。

    这里**故意不从环境变量或 qwen_env.sh 里读**：那等于把 key 写进笔记本，
    镜像分享出去后，任何能打开 JupyterLab 的人都能拿到。
    改成运行时输入一次，只留在当前内核内存里。
    """
    try:
        return getpass.getpass("输入 API Key（= 服务端 QWEN_API_KEY；没启用鉴权就直接回车）：").strip()
    except Exception:
        return ""
'''

SVC_HELPER = '''import re

def service_url():
    """读 AutoDL 写在容器里的公网入口。

    别用 /jupyter/proxy/6006/：Jupyter 只是原样转发，服务收到的路径会带
    /jupyter/proxy/6006 前缀，路由匹配不上 → 404。
    """
    try:
        txt = open("/init/others/help", encoding="utf-8", errors="replace").read()
        m = re.search(r"AutoDLService6006URL=(\\S+)", txt)
        if m:
            return m.group(1).rstrip("/")
    except Exception:
        pass
    return "http://127.0.0.1:6006"
'''


def md(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(keepends=True)}


def py(text):
    return {"cell_type": "code", "execution_count": None, "metadata": {},
            "outputs": [], "source": text.splitlines(keepends=True)}


CELLS = [

md("""# Qwen-Image-2.1 控制台

这个笔记本把常用操作做成了**点一下就跑**的格子。左侧目录里 `service/` 是代码、`outputs/` 是出图目录。

**建议按顺序点**：先点第 1 格启动服务，再点第 2 格开界面，后面的格子按需用。

> 说明：这个实例上服务的启动/停止/看日志/调接口，全部封装在上面的格子按钮里，不用敲命令。
"""),

md("""---
## 1 · 启动 / 重启服务

▶ 之后等 1~2 分钟（要把 33 GB 权重灌进显存），下面的状态会自动变成「服务就绪」。
关掉笔记本不会停服务；要停就点「停止服务」。

按钮在部分 JupyterLab 版本上可能不弹新格子（Jupyter 的按钮注入机制各版本不同）。
**按钮失效时的保底办法**：把下一格里的 `ACTION` 改成对应动作，直接 ▶ 运行那一格 —— 这条路任何版本都通。"""),

py("""import os, subprocess, time, json, urllib.request
from IPython.display import display, HTML
""" + SVC_HELPER + KEY_HELPER + """
ROOT = "/root/qwen-image-2.1"
BASE = "http://127.0.0.1:6006"
KEY  = read_key()
if KEY:
    print("  key 长度:", len(KEY), "（只留在本内核内存里，不落盘）")

# ─────────────────────────────────────────────────────────────
#  改这一行，然后运行本格：  start | restart | stop | status | url
ACTION = "status"
# ─────────────────────────────────────────────────────────────

CMDS = {
    "start":   "bash /root/qwen-image-2.1/scripts/serve.sh start",
    "restart": "bash /root/qwen-image-2.1/scripts/serve.sh restart",
    "stop":    "bash /root/qwen-image-2.1/scripts/serve.sh stop",
    "status":  "bash /root/qwen-image-2.1/scripts/serve.sh status",
    "url":     "bash /root/qwen-image-2.1/scripts/show_url.sh",
}

def sh(cmd, timeout=600):
    p = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True, timeout=timeout)
    return (p.stdout or "") + (p.stderr or "")

def health(timeout=8):
    try:
        with urllib.request.urlopen(BASE + "/health", timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None

def running():
    return bool(sh("pgrep -f 'service/server.py' | head -1"))

cmd = CMDS.get(ACTION)
if cmd:
    print(f"$ {cmd}")
    print(sh(cmd))
else:
    print("ACTION 只能是：", ", ".join(CMDS))

h = health()
print("─" * 60)
print("服务进程：", "在跑" if running() else "没在跑")
if h:
    g = h.get("gpu") or {}
    print(f"接口状态：就绪  loaded={h['loaded']}  mock={h['mock']}")
    print(f"显存      ：空闲 {g.get('free_gb')}G / 已用 {g.get('reserved_gb')}G "
          f"/ 总 {g.get('total_gb')}G")
    print(f"当前任务  ：{h.get('active') or '空闲'}")
else:
    print("接口状态：连不上 —— 把上面 ACTION 改成 start 再跑一次这格")
"""),

py("""from IPython.display import display, HTML
import json as _json

# 三个顺手按钮。点了没反应（部分 JupyterLab 版本会禁掉这种注入）就用上一格改 ACTION。
_CMD = "ACTION = 'start'"
_BTN = '''
<div style="margin:6px 0 12px 0">
  <button onclick="(function(){
      var code = %s;
      var nb = (typeof Jupyter !== 'undefined') ? Jupyter.notebook : null;
      if (nb) {
        var i = nb.get_selected_index();
        nb.insert_cell_below('code', i);
        var c = nb.get_cell(i + 1); c.set_text(code); c.execute();
      } else {
        navigator.clipboard.writeText(code);
        alert('当前 JupyterLab 不支持按钮注入，命令已复制：\\n' + code
              + '\\n\\n粘到新格子执行即可。');
      }
    })()"
    style="padding:8px 16px;margin-right:8px;border:0;border-radius:8px;background:#1f6feb;
           color:#fff;font-weight:600;cursor:pointer">▶ 启动服务</button>
  <button onclick="(function(){
      var code = %s;
      var nb = (typeof Jupyter !== 'undefined') ? Jupyter.notebook : null;
      if (nb) {
        var i = nb.get_selected_index();
        nb.insert_cell_below('code', i);
        var c = nb.get_cell(i + 1); c.set_text(code); c.execute();
      } else {
        navigator.clipboard.writeText(code);
        alert('命令已复制：\\n' + code);
      }
    })()"
    style="padding:8px 16px;margin-right:8px;border:0;border-radius:8px;background:#8957e5;
           color:#fff;font-weight:600;cursor:pointer">⟳ 重启服务</button>
  <button onclick="(function(){
      var code = %s;
      var nb = (typeof Jupyter !== 'undefined') ? Jupyter.notebook : null;
      if (nb) {
        var i = nb.get_selected_index();
        nb.insert_cell_below('code', i);
        var c = nb.get_cell(i + 1); c.set_text(code); c.execute();
      } else {
        navigator.clipboard.writeText(code);
        alert('命令已复制：\\n' + code);
      }
    })()"
    style="padding:8px 16px;border:1px solid #30363d;border-radius:8px;background:#21262d;
           color:#e6edf3;font-weight:600;cursor:pointer">🩺 看状态</button>
</div>''' % (_json.dumps("ACTION = 'start'"),
            _json.dumps("ACTION = 'restart'"),
            _json.dumps("ACTION = 'status'"))

display(HTML(_BTN))
print("按钮不灵就用上一格：把 ACTION 改成 start / restart / stop / status / url，再运行。")
"""),

md("""---
## 2 · 打开图形界面（WebUI）

下面两个链接走 JupyterLab 的代理（`/jupyter/proxy/6006/`），所以**不需要额外开隧道**。
**API Key 会自动填好**，不用手输。"""),

py("""from IPython.display import display, HTML
""" + SVC_HELPER + """
if not SVC:
    print("没读到公网入口，用 JupyterLab 侧边栏或控制台复制；本机访问是 http://127.0.0.1:6006/")

display(HTML(f'''
<a href="{SVC}/" target="_blank"
   style="display:inline-block;padding:10px 20px;border-radius:8px;background:#238636;
          color:#fff;font-weight:600;text-decoration:none">
   🖼 打开 Qwen 控制台（新标签页）</a>
<a href="{SVC}/docs" target="_blank"
   style="display:inline-block;margin-left:10px;padding:10px 20px;border-radius:8px;
          background:#21262d;color:#e6edf3;font-weight:600;text-decoration:none;
          border:1px solid #30363d">
   📘 打开接口文档（Swagger）</a>
'''))
print()
print("服务入口：", SVC or "（未读到）")
print("控制台会问一次 API Key —— 就是服务端 QWEN_API_KEY 的值，输入后浏览器会记住。")
print()
print("注意：不要用 /jupyter/proxy/6006/ 这个路径，服务收到的路径会带前缀，会 404。")
"""),

md("""---
## 3 · 服务入口 / 端口 一览

实例上有这些东西在监听，**端口需要在实例开机状态下才通**："""),

py("""import re, os, socket
""" + SVC_HELPER + """
def read(path):
    try:
        return open(path, encoding="utf-8", errors="replace").read()
    except Exception:
        return ""

txt = read("/init/others/help")
def svc(port, field="URL"):
    m = re.search(rf"AutoDLService{port}{field}=(\\S+)", txt)
    return m.group(1) if m else ""

pub6006, pub6008 = svc(6006), svc(6008)
tok = ""
m = re.search(r'ServerApp\\.token\\s*=\\s*"([^"]+)"', read("/init/jupyter/jupyter_config.py"))
if m:
    tok = m.group(1)

print("=" * 92)
print("监听端口")
print("=" * 92)
rows = [
    ("6006", "Qwen-Image-2.1 服务", "WebUI 控制台 + REST API", pub6006 or "（未读到映射）"),
    ("8888", "JupyterLab",         "就是你现在这个页面",       "控制台点「JupyterLab」按钮"),
    ("6007", "TensorBoard",        "镜像自带，本项目没用",     "—"),
    ("6008", "备用映射端口",        "当前没人监听",            pub6008 or "—"),
]
for p, name, use, url in rows:
    print(f"  {p:<5} {name:<20} {use:<24} {url}")

print()
print("同机访问（容器内部 / 脚本用）")
print("  WebUI + API   http://127.0.0.1:6006/")
try:
    ip = socket.gethostbyname(socket.gethostname())
    print(f"  容器内网 IP   http://{ip}:6006/")
except Exception:
    pass
print("  JupyterLab    http://127.0.0.1:8888/jupyter/")
print()
print("JupyterLab 的 base_url 是 /jupyter/，所以反代其它服务的规律是：")
print("  /jupyter/proxy/<端口>/        例如 /jupyter/proxy/6006/")
print("  文件浏览/下载                  /jupyter/files/<root 之后的路径>")
print()
if tok:
    print("JupyterLab token（浏览器里已记住，一般不用手输）：")
    print("  " + tok)
"""),

md("""---
## 4 · 输出目录（出图都在这）

下面列出 `outputs/` 里的图片并直接预览，点图可看原图。重新运行本格即可刷新。"""),

py("""import os, glob, time, urllib.parse
from IPython.display import display, HTML

OUT_DIRS = ["/root/qwen-image-2.1/outputs"]
JROOT = "/root"                      # JupyterLab 的 root_dir

files = []
for d in OUT_DIRS:
    for ext in ("png", "jpg", "jpeg", "webp"):
        files += glob.glob(os.path.join(d, f"*.{ext}"))
files.sort(key=lambda f: os.path.getmtime(f), reverse=True)

def jurl(path):
    rel = os.path.relpath(path, JROOT)
    return "/jupyter/files/" + urllib.parse.quote(rel)

print(f"共 {len(files)} 张 · 目录 {', '.join(OUT_DIRS)}")
if not files:
    print("还没有图。用第 5 格直接调 API 出一张，或打开第 2 格的控制台画一张。")
else:
    cards = []
    for f in files[:36]:
        cards.append(
            f'<div style="display:inline-block;margin:6px;text-align:center;vertical-align:top">'
            f'<a href="{jurl(f)}" target="_blank">'
            f'<img src="{jurl(f)}" loading="lazy" '
            f'style="width:148px;height:148px;object-fit:cover;border-radius:8px;'
            f'border:1px solid #30363d;display:block"></a>'
            f'<div style="font-size:11px;color:#8b949e;margin-top:4px;max-width:148px;'
            f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'
            f'{os.path.basename(f)}<br>{os.path.getsize(f)/1024:.0f} KB · '
            f'{time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(f)))}</div></div>')
    display(HTML("".join(cards)))
    print("下载全部：在左侧文件树里右键 outputs 目录 → Download。")
"""),

md("""---
## 5 · 不打开界面，直接用 API 出一张图

改 `PROMPT` 然后 ▶。图片会存到 `outputs/` 并显示出来。

`KEY` 由本格**运行时输入**（不从环境变量读 —— 免得被写进镜像分享出去）。"""),

py("""import json, base64, time, os, urllib.request, re

def read_key():
    import getpass
    try:
        return getpass.getpass("输入 API Key（服务端 QWEN_API_KEY；没启用鉴权就直接回车）：").strip()
    except Exception:
        return ""

PROMPT   = "a lighthouse in a storm, huge waves, dramatic clouds, cinematic"   # ← 改这里
WIDTH    = 1024
HEIGHT   = 1024
STEPS    = 20
SEED     = 42            # 置 None 则随机
TRANSPARENT = False

KEY  = read_key()
BASE = "http://127.0.0.1:6006"

body = {"prompt": PROMPT, "width": WIDTH, "height": HEIGHT,
        "num_inference_steps": STEPS, "transparent": TRANSPARENT}
if SEED is not None:
    body["seed"] = SEED

req = urllib.request.Request(BASE + "/v1/images/generations",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
t0 = time.time()
try:
    with urllib.request.urlopen(req, timeout=1800) as r:
        data = json.loads(r.read())
except Exception as e:
    print("失败：", type(e).__name__, e)
    print()
    print("  服务起来了吗？把上一格的 ACTION 改成 start 跑一遍。")
    print("  401 的话是 key 不对：看 /root/qwen-image-2.1/qwen_env.sh 里的 QWEN_API_KEY。")
else:
    item = data["data"][0]
    raw = base64.b64decode(item["b64_json"])
    out = f"/root/qwen-image-2.1/outputs/api_{time.strftime('%H%M%S')}.png"
    open(out, "wb").write(raw)
    tm = item.get("timing", {})
    print(f"完成 {item['width']}×{item['height']} · {time.time()-t0:.1f}s"
          f" · 每步 {tm.get('per_step_s')}s · seed={item.get('seed')}")
    print("已存：", out)
    from IPython.display import Image as _I
    display(_I(filename=out, width=520))
"""),

md("""---
## 6 · 边跑边看进度

第 5 格在跑的时候，另开一个格子贴这段，就能看到**真实步数 / 每步耗时 / 预计剩余**。
（服务端把每一步的回调都记在 `/v1/progress` 上，不是按时间猜的。）"""),

py("""import time, json, urllib.request

def read_key():
    import getpass
    try:
        return getpass.getpass("输入 API Key：").strip()
    except Exception:
        return ""

KEY  = read_key()
BASE = "http://127.0.0.1:6006"
WATCH_SECONDS = 30          # 想多看一会儿就把这个调大

def _get(p):
    r = urllib.request.Request(BASE + p, headers={"Authorization": "Bearer " + KEY})
    return json.loads(urllib.request.urlopen(r, timeout=15).read())

t0 = time.time()
last = None
while time.time() - t0 < WATCH_SECONDS:
    try:
        data = _get("/v1/progress")["data"]
        cur = next((p for p in data if p["status"] in ("running", "queued")), None) or (data[0] if data else None)
        if cur:
            line = (f"[{cur['status']:8s}] {cur['steps_done']:>3d}/{cur['total']:<3d} "
                    f"{cur['pct']:5.1f}%  已用 {cur['elapsed_s']}s  "
                    f"每步 {cur['per_step_s']}s  ETA {cur['eta_s']}s")
            if line != last:
                print(line); last = line
        else:
            print("当前没有任务在跑"); break
    except Exception as e:
        print("读取失败：", e); break
    time.sleep(1.0)
print("\\n看完了。要一直盯就调大 WATCH_SECONDS 重跑本格。")
"""),

md("""---
## 7 · 上传图片（给图像编辑用）

选文件 → 存进 `inputs/`。图像编辑要用它的话：打开第 2 格的控制台，把图片拖进「参考图」框最省事；
或者在下面的格子里直接调 `/v1/images/edits`。"""),

py("""import os, time
from IPython.display import display, clear_output

IN_DIR = "/root/qwen-image-2.1/inputs"
os.makedirs(IN_DIR, exist_ok=True)

def _save_bytes(name, content):
    dst = os.path.join(IN_DIR, name)
    if os.path.exists(dst):
        stem, ext = os.path.splitext(name)
        dst = os.path.join(IN_DIR, f"{stem}_{int(time.time())}{ext}")
    with open(dst, "wb") as fh:
        fh.write(content)
    print(f"已保存 {dst}  ({len(content)/1024:.0f} KB)")

try:
    import ipywidgets as widgets

    picker = widgets.FileUpload(accept="image/*", multiple=True, description="选图片")
    btn = widgets.Button(description="保存到 inputs/", button_style="success")
    out = widgets.Output()

    def _save(_):
        # ipywidgets 7 是 dict{name: {...}}，8 是 tuple[dict]；两种都兜住
        v = picker.value
        items = []
        if isinstance(v, dict):
            items = list(v.values())
        elif isinstance(v, (list, tuple)):
            items = list(v)
        with out:
            clear_output()
            if not items:
                print("还没选文件")
            for it in items:
                if isinstance(it, dict):
                    _save_bytes(it.get("name", "upload.png"), it.get("content", b""))
                else:                      # ipywidgets 8 的 FileUpload 对象
                    _save_bytes(getattr(it, "name", "upload.png"), getattr(it, "content", b""))
        picker.value = [] if isinstance(v, (list, tuple)) else {}

    btn.on_click(_save)
    display(widgets.HBox([picker, btn]), out)
except Exception as e:
    print("ipywidgets 不可用（", type(e).__name__, "），改用下面这行的办法：")
    print("  在左侧文件树里右键 inputs/ → Upload，把图直接拖进去")

print()
print("图片目录：", IN_DIR)
for f in sorted(os.listdir(IN_DIR))[:20]:
    p = os.path.join(IN_DIR, f)
    if os.path.isfile(p):
        print(f"   {f}  ({os.path.getsize(p)/1024:.0f} KB)")
"""),

md("""---
## 8 · API 速查

### 鉴权
所有 `/v1/*`、`/docs`、`/openapi.json` 都要 key；`/`（控制台）和 `/health` 不需要。

两种带法等价：
```bash
curl -H "Authorization: Bearer <你的KEY>" https://<入口>/v1/models
curl "https://<入口>/v1/models?key=<你的KEY>"
```

### 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` · `/ui` | 控制台页面（免鉴权，key 自动注入） |
| GET | `/health` | 服务状态：loaded / GPU 显存 / 队列 / 当前进度（免鉴权） |
| GET | `/v1/models` | 模型列表 |
| POST | `/v1/images/generations` | 文生图（同步，JSON） |
| POST | `/v1/images/edits` | 图像编辑（同步，multipart，最多 10 张参考图） |
| POST | `/v1/jobs` | 异步提交，返回 job_id |
| GET | `/v1/jobs` · `/v1/jobs/{id}` | 任务列表 / 查询 |
| DELETE | `/v1/jobs/{id}` | 取消排队中的任务 |
| GET | `/v1/progress` | 最近任务的**真实步进进度**（步数/每步耗时/ETA） |
| GET | `/v1/progress/{request_id}` | 单个任务的进度 |
| POST | `/v1/admin/empty_cache` | 把分配器缓存还给驱动（跑 2K 前建议调一次） |
| GET | `/docs` · `/redoc` · `/openapi.json` | 接口文档（需 key，`/docs?key=<你的KEY>` 直接打开） |

### 关键参数

**文生图 `POST /v1/images/generations`**

| 字段 | 默认 | 说明 |
|---|---|---|
| `prompt` | 必填 | 提示词 |
| `num_inference_steps` | 40 | 步数；20~25 可明显提速 |
| `width` / `height` | 2048×2048 | 显式尺寸 |
| `aspect_ratio` | — | `1:1 4:3 3:4 3:2 2:3 16:9 9:16` 官方档位 |
| `seed` | 随机 | 复现用 |
| `transparent` | false | 透明背景 RGBA PNG |
| `guidance_scale` / `negative_prompt` | — | 可选 |
| `request_id` | 自动 | 想自己轮询进度就带上 |

**图像编辑 `POST /v1/images/edits`**（multipart）

| 字段 | 说明 |
|---|---|
| `prompt` | 必填 |
| `image` | 参考图，可重复最多 10 次 |
| `num_inference_steps` | 默认 40 |
| `output_resolution` | **控制输出边长的真旋钮**（默认 1024 → 出 832×1248；1280 → 1056×1568，约 2 倍耗时） |
| `width` / `height` | 实测会被模型忽略，别指望 |
| `seed` / `transparent` / `request_id` | 同上 |

### 响应（同步）

```json
{"created": 1790397205, "model": "Qwen-Image-2.1", "size": "1024x1024",
 "data": [{"b64_json": "iVBORw0KGgo...", "seed": 42, "width": 1024, "height": 1024,
           "mode": "RGBA", "elapsed_s": 11.2,
           "timing": {"request_id": "req_xxx", "total_s": 11.2, "prep_s": 0.0,
                      "steps": 20, "per_step_s": 0.51,
                      "durations": [0.50, 0.50, ...], "callback_ok": true}}]}
```

### 进度对象 `GET /v1/progress`

```json
{"request_id": "req_xxx", "status": "running",     // queued|running|done|error
 "step": 12, "steps_done": 12, "total": 20, "pct": 60.0,
 "elapsed_s": 7.03, "eta_s": 4.1, "per_step_s": 0.514,
 "last_step_s": 0.503, "min_step_s": 0.455, "max_step_s": 0.697,
 "callback_unavailable": false, "queue_depth": 0, "error": null}
```

### 实测耗时（供估算）

| 场景 | 耗时 |
|---|---|
| 512×512 / 8 步 | ~1.8 s |
| 1024×1024 / 20 步 | ~11 s（约 0.51 s/步） |
| 2048×2048 / 40 步 | ~115 s（需开分块 VAE） |
| 编辑 1 张参考图 / 30~35 步 | ~21~24 s |

> 显存占用：权重常驻 30.2 G，2048² 时进程整卡约 34 G（单卡 48 G 够用）。
"""),

md("""---
## 9 · 常见问题

**Q：服务状态显示「连不上」**
回第 1 格点「启动服务」。实例重启后服务不会自动起，需要手动点一次（或用 `serve.sh start`）。

**Q：WebUI 打不开**
用第 2 格的按钮（走 `/jupyter/proxy/6006/`）。如果还是不行，回第 1 格看「状态 / 日志尾部」。

**Q：出图很慢**
检查步数（40 步是官方默认，20~25 步快一倍）和分辨率（2048² 比 1024² 慢约 10 倍）。
编辑接口想快就把 `output_resolution` 留在默认。

**Q：显存不够 / CUDA OOM**
先调一次 `POST /v1/admin/empty_cache`（长跑会把缓存攥住十几 G）；
2048² 出图必须开分块 VAE（`serve.sh` 已默认 `QWEN_TILE_VAE=1`）。

**Q：改 key**
改 `/root/qwen-image-2.1/qwen_env.sh` 里的 `QWEN_API_KEY`，然后点「重启服务」。控制台会自动同步新 key。
"""),
]


def main():
    nb = {
        "cells": CELLS,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.12.3"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(nb, fh, ensure_ascii=False, indent=1)
    print("wrote", OUT, os.path.getsize(OUT), "bytes,", len(CELLS), "cells")


if __name__ == "__main__":
    main()
