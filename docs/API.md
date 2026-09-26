# Qwen-Image-2.1 HTTP API（AutoDL 部署）

## 0. 当前部署状态

| 项 | 值 |
|---|---|
| 实例 | `ssh -p <端口> root@connect.west?.seetacloud.com` |
| 区域 / GPU | 西部 B 区，**48G 单卡（魔改 4090，AD102 / sm_89，无 NVLink）** |
| 镜像 | PyTorch 2.8.0 + cu128 + Python 3.12.3（`/root/miniconda3`） |
| 模型 | `Qwen/Qwen-Image-2.1`，本地路径 `/root/autodl-tmp/Qwen-Image-2.1`，33.13 GB |
| 依赖 | transformers 5.17.0 · diffusers 0.41.0.dev0 (git main) · accelerate 1.15.0 · torch 2.8.0+cu128 |
| 服务 | `/root/qwen-image-2.1/service/server.py`（FastAPI + uvicorn，端口 6006） |
| 环境脚本 | `source /root/qwen-image-2.1/qwen_env.sh` |
| 启停脚本 | `bash /root/qwen-image-2.1/scripts/serve.sh start|stop|status|fg` |
| 跑分脚本 | `python /root/qwen-image-2.1/scripts/bench.py [--quick] [--offload]` |

**48G 卡显存账（决定默认参数）**

| 组成 | BF16 占用 |
|---|---|
| DiT 7B（32 层 single-stream） | 14.23 GB |
| Qwen3-VL 8B 文本编码器 | 17.53 GB |
| RGBA VAE | 1.35 GB |
| 权重小计 | **≈ 33.1 GB** |
| 2048² 序列的 latent / attention 中间量 | ≈ 8 GB（随像素线性缩放） |
| 4096 token prefix KV cache | ≈ 4 GB（CFG=1 时一份） |
| 余量 | 剩 3~7 GB，够；再往上加参考图就得开 offload |

结论：`QWEN_OFFLOAD=none` 全常驻显存可行，`QWEN_PRELOAD=1` 启动即加载；只有多参考图编辑 + 2K 同时上才需要改成 `model`。带宽吃紧（GDDR6X ~1 TB/s，且这张卡显存是 24GB→48GB 魔改），所以显存换带宽是划算的，别为了省显存去开 `sequential` offload。

### 0.1 实测性能（2026-09-26，克隆机 4090 48G，全 BF16 常驻）

| 场景 | 分辨率 / 步数 | 耗时 | 峰值显存 |
|---|---|---|---|
| 文生图 | 512×512 / 8 步 | 1.8 s | — |
| 文生图 | 1024×1024 / 20 步 | 10.9 s（0.54 s/步） | 36.8 GiB |
| 文生图 | 1024×1024 / 25 步 | 13.9 s | 36.8 GiB |
| 文生图 | 2048×2048 / 40 步（分块 VAE） | 115.3 s（2.88 s/步） | 32.5 GiB |
| 图像编辑 | 单参考图 → 832×1248 / 30 步 | 21.3 s | 38.8 GiB |

权重常驻 30.23 GiB，服务进程整卡占用约 33~34 GiB，`nvidia-smi` 常驻约 32 GiB。

**必读的两条实测约束**

1. **2048² 必须开分块 VAE 解码**（`QWEN_TILE_VAE=1`）：不开时 DiT 采样能过，最后在 VAE 上采样层炸 `CUDA out of memory (Tried to allocate 4.50 GiB)`。镜像里的 `serve.sh` 已经默认带上这个变量和 `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`。
2. **编辑接口的输出尺寸会被模型往下取一档**：给 1696×2528 的参考图，不传 `width`/`height` 时输出 832×1248。真正的旋钮是管线参数 **`output_resolution`**（默认 1024，决定去噪分辨率与实际输出边长），现在已透出到接口。实测 `output_resolution=1280` → 输出 1056×1568、单张 50.8s（约 2 倍耗时），但**不会**改善人脸保持一致的程度。

### 0.2 多步编辑链实测（2026-09-26）

四步链（姿势 → 表情/头部 → 手 → 机位），每步把上一步输出当输入，同 seed=22，35 步。指标：`identity_ssim` 是与原始输入的相似度，`face_drift` 是人脸区域的像素漂移（越小越像原图）。

| 步骤 | 耗时 | 相对上一步 SSIM | 人脸漂移（vs 原图） |
|---|---|---|---|
| 1 姿势（改动最大） | 23.7 s | 0.269 | **0.180** |
| 2 表情 | 23.4 s | 0.616 | 累计 0.223 |
| 3 手 | 23.6 s | 0.846 | 累计 0.215 |
| 4 机位 | 23.9 s | 0.892 | 累计 0.211 |

三条结论，都是实验得出的：

1. **每一步都会重绘整张图，包括脸。** 第一步只要求改姿势，人脸区域的像素漂移就已经到 0.18，和整图漂移（0.177）基本一样大。四步链跑完，与原始输入的 SSIM 只剩 **0.138**——脸已经不是原来那张脸了。
2. **提示词里的 KEEP 段落几乎不起作用。** 对照组 A（"Keep the same character, same face..."长句）与 B（`KEEP:` / `CHANGE:` 分块的清单式写法）数值几乎逐位重合（0.2691 vs 0.2501，0.6163 vs 0.6064……），说明换措辞无效。
3. **拿原图当第二张参考图（锚定）不但没用，还会更差。** `image=[当前图, 原图]` 时人脸漂移从 0.172 掉到 0.179~0.203，单张耗时从 24.5s 涨到 28.4s（第二张参考图的 prefix KV 缓存额外吃约 8 GiB 显存）。

**结论：想靠提示词工程在链式编辑里锁住人脸，这条路是死的。** 保持一致性只能靠链路之外的补偿手段（把原图人脸区域做软边合成贴回、或者干脆用单步编辑 instead of 多步链）。

```bash
# 实例上启动（后台）
bash /root/qwen-image-2.1/scripts/serve.sh start
curl -s localhost:6006/health | python -m json.tool
```

两种运行模式由 `QWEN_MODE` 控制：

- `auto`（默认）：检测到 GPU 才真跑推理；无卡模式下返回占位图，用于联调契约。
- `real`：无 GPU 时直接返回 `409 no GPU attached`，避免上游拿到假图。
- `mock`：从不碰 GPU，永远返回占位图。

---

## 1. 接入地址

服务监听 `0.0.0.0:6006`。三种接法：

| 方式 | 地址 | 说明 |
|---|---|---|
| **浏览器控制台（WebUI）** | `https://<实例ID>.westb.seetacloud.com:8443/` | 根路径就是控制台 |
| Swagger 接口文档 | `https://<实例ID>.westb.seetacloud.com:8443/docs` | 可直接试调 |
| 备用端口 6008 | `https://<端口6008前缀>-<实例ID>.westb.seetacloud.com:8443/` | 映射同一个容器，换个域名前缀 |
| 同内网/同机器 | `http://127.0.0.1:6006` | 其他容器进程直接调，`/` 也是控制台 |
| SSH 隧道（无企业认证时） | `ssh -p <端口> -L 16006:127.0.0.1:6006 root@connect.west?.seetacloud.com` → `http://127.0.0.1:16006` | 本地开发/调试用 |

**公网地址不用去控制台翻**：AutoDL 把映射写在容器的 `/init/others/help` 里，一条命令就能打印：

```bash
bash /root/qwen-image-2.1/scripts/show_url.sh
# AutoDLService6006URL=https://<实例ID>.westb.seetacloud.com:8443
# AutoDLService6008URL=https://<端口6008前缀>-<实例ID>.westb.seetacloud.com:8443
```

实测（2026-09-26）：`/`、`/health`、`/docs`、`/v1/models` 经公网入口全部 HTTP 200，
根路径 17690 字节，健康检查 258ms。截图见 `reports/webui-public.png`。

**WebUI**（`service/ui/index.html`，纯静态单页，无构建步骤、不依赖 Gradio）：
文生图 / 图像编辑两个模式切换、prompt、宽高与官方宽高比档位、步数滑杆、seed、透明 RGBA、
异步排队开关、编辑专用的 `output_resolution`；右侧显示耗时 / 尺寸 / seed / 峰值显存，
支持下载、复用参数、会话内历史（缩略图可点开）。

> 端口 6006 的公网映射需要实例处于**开机状态**，且服务进程要在实例内常驻；重启实例后 `serve.sh start` 需要再执行一次（或用 systemd 单元托管）。

---

## 2. 通用约定

- 传输：JSON（`/v1/images/generations`、`/v1/jobs`）或 `multipart/form-data`（`/v1/images/edits`）。
- **鉴权**（`QWEN_API_KEY` + `QWEN_API_KEYS`）：
  - **支持多个 key 同时有效**：`QWEN_API_KEY` 是主 key，`QWEN_API_KEYS` 里可再列若干个
    （逗号/分号/空格分隔），任意一个都能通过。用途：换 key 时给旧的留过渡期、
    或给自己人一个短口令对外用长随机串。
  - 受保护：`/v1/*` 全部（含 `/v1/progress*`、`/v1/session`）、`/docs`、`/redoc`、`/openapi.json`
  - 不受保护：`/`（控制台页面）、`/ui`、`/health`（存活探测用）
  - 三种带法，任一成立即可：

    | 带法 | 用在哪 |
    |---|---|
    | `Authorization: Bearer <key>` | 脚本、上游服务 |
    | `?key=<key>` | 浏览器直接跳转、`<img>`/`<a>` 这类发不了 header 的场景 |
    | **Cookie `qwensess`**（登录后服务端下发） | 浏览器控制台 —— JS 读不到，也不存本地 |

  - key 比较用 `secrets.compare_digest`（常量时间），避免时序侧信道。
  - **控制台不再保存 API Key**：`POST /v1/session` 用 key 换一个
    **HttpOnly + SameSite=strict + Secure** 的会话 Cookie（有效期 `QWEN_SESSION_HOURS`，默认 24h）。
    页面 JS 从头到尾看不到明文 key，XSS 也偷不走 Cookie；「退出」会调 `DELETE /v1/session`
    让服务端销毁会话。
  - `QWEN_UI_KEY` 只决定是否把 key 填进「直连排障」输入框：

    | 值 | 行为 | 用在哪 |
    |---|---|---|
    | `inject` | key 渲染进页面并填好（仅排障用） | 只有自己用 |
    | `auto`（默认） | 不注入；浏览器走登录 → Cookie 会话 | 分享镜像 / 给别人用 |
    | `off` | 页面按无鉴权工作（要求所有 key 都为空） | 明确不鉴权时 |
- 图片回传：`data[].b64_json`（base64，默认 PNG）。透明图原生带 alpha 通道。
- 尺寸：`width`/`height` 显式给像素，或 `size:"WxH"`，或 `aspect_ratio` 用官方推荐档位（`1:1` 2048×2048 等）。
  控制台里选了档位会把宽高输入框置灰（尺寸由后端按档位解析）。
- **输出尺寸的真实规则**（实测 + 读 diffusers 源码，见 `docs/MEASUREMENTS.md` 3.2）：
  `output_resolution` 是**像素预算**（预算 = 分辨率的平方），**比例取自参考图**，
  而**显式 `width`/`height` 优先级最高**。举例：768×1024 参考图 + `output_resolution=1024`
  → 输出 896×1184；加上 `width=1184&height=1600` → 就出 1184×1600。
- **编辑模式的分辨率上限约 1.92MP**（1184×1600 通过 / 1280×1696 OOM，48G 卡全常驻时），
  原生 2K（1696×2528）编辑会 OOM，只能开 `QWEN_OFFLOAD=model`。
  文生图不受此限（2048² 正常，但**必须开分块 VAE**，`serve.sh` 已默认开）。
- **控制台会记住上次的输入内容**（prompt / 宽高 / 步数 / seed / 档位 / 开关，存 localStorage 的
  `qwen_form_v1`）。**只记输入内容，不记 key**。编辑模式下宽高旁会按实测边界提示显存风险。
- 并发：单卡串行，服务内部有 GPU 锁；排队深度见 `/health.queue_depth`。批量请用 `/v1/jobs`。

> 安全提示：key 的作用是挡住扫端口的陌生人。Cookie 会话让页面里不再出现明文 key，
> 但**地址 + key 一起外传仍然等于没设防**。要防"拿到 key 的人刷爆显卡"，还需要速率限制/配额，
> 当前没做，所以**公网地址只适合小圈子自用**。

```bash
# 命令行三种带法
curl -H "Authorization: Bearer <你的KEY>" https://<入口>/v1/models
curl "https://<入口>/v1/models?key=<你的KEY>"
curl "https://<入口>/docs?key=<你的KEY>"        # Swagger，可直接试调

# 换会话 Cookie（浏览器控制台走的就是这条）
COOKIE=$(curl -s -D - -o /dev/null -X POST https://<入口>/v1/session \
  -H 'Content-Type: application/json' -d '{"key":"<你的KEY>"}' \
  | grep -i '^set-cookie' | sed -E 's/^[Ss]et-[Cc]ookie: ([^;]+).*/\1/' | tr -d '\r')
curl -H "Cookie: $COOKIE" https://<入口>/v1/models
```

---

## 3. 端点

### 3.1 `GET /health`（免鉴权）

返回里额外带 `auth_required` / `ui_key_mode` / `session_ttl_h`，方便排障时确认鉴权配置。

```json
{
  "status": "ok",
  "model": "Qwen-Image-2.1",
  "loaded": true,
  "mode": "auto",
  "mock": false,
  "checkpoint": {"dir": "/root/autodl-tmp/Qwen-Image-2.1", "present": true},
  "dtype": "bfloat16",
  "offload": "none",
  "queue_depth": 0,
  "gpu": {"available": true, "name": "NVIDIA A40", "total_gb": 48.0, "free_gb": 44.1,
           "allocated_gb": 0.0, "reserved_gb": 0.0, "capability": "8.6"}
}
```

### 3.2 `GET /v1/models`

```json
{"object": "list", "data": [{"id": "Qwen-Image-2.1", "object": "model", "owned_by": "qwen"}]}
```

### 3.3 `POST /v1/images/generations` — 统一入口（`image` 可选）

> **只有一条路径**：底层是同一个 `QwenImage21Pipeline`，`image` 传了就是条件生成、
> 不传就是纯文本生成。所以这个端点**同时承担"文生图"和"图像编辑/多主体合成"**，
> 而且请求体两种都收（JSON 用 `image_b64`，multipart 用重复的 `image` 字段）。
> `/v1/images/edits` 保留为别名（转发到同一实现），只是历史命名。

请求：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `prompt` | string | 必填 | 提示词；透明图建议带 `RGBA image with transparency` |
| `image` | file ×N | — | **可选**参考图（multipart，最多 10 张）；传了就走条件生成 |
| `image_b64` | string[] | — | JSON 请求体里的参考图（base64 数组，可带 `data:` 前缀） |
| `num_inference_steps` | int | 40 | 20~25 可明显提速 |
| `width` / `height` | int | 2048×2048 | 显式尺寸 |
| `size` | string | — | `"2048x2048"` 形式，优先级低于 width/height |
| `aspect_ratio` | string | — | `1:1 4:3 3:4 3:2 2:3 16:9 9:16` |
| `seed` | int | 随机 | 复现用 |
| `transparent` | bool | false | true 时服务自动补官方透明提示词前缀，输出 RGBA |
| `output_format` | string | `png` | `png` / `jpeg` / `webp` |
| `guidance_scale` | float | 管线默认 | 官方推荐 CFG=1 时可直接给 1.0 |
| `negative_prompt` | string | — | 可选 |

```bash
curl -s -X POST "http://127.0.0.1:6006/v1/images/generations" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"A neon shop sign that reads \"QWEN IMAGE 2.1\", rainy night, reflections on wet pavement",
       "num_inference_steps":40,"width":2048,"height":2048,"seed":42}' \
  | python -c "import sys,json,base64;d=json.load(sys.stdin);open('out.png','wb').write(base64.b64decode(d['data'][0]['b64_json']))"
```

响应：

```json
{
  "created": 1787000000,
  "model": "Qwen-Image-2.1",
  "size": "2048x2048",
  "data": [{"b64_json": "iVBORw0K...", "seed": 42, "width": 2048, "height": 2048,
            "mode": "RGBA", "elapsed_s": 96.4}]
}
```

### 3.3.1 参考图怎么在 prompt 里点名（`<image1>` / `<image2>` …）

**结论：官方就是这个语法，编号 = 上传顺序，从 1 开始数。**

管线源码 `docs/upstream/diffusers-pipeline_qwenimage21.py` L216-259 写得很直白：

```python
self.prompt_template_ti2i = (
    f"<|im_start|>system\n{self.sys_prompt}<|im_end|>\n"
    f"<|im_start|>user\n<image1><|vision_start|><|image_pad|><|vision_end|>{{}}<|im_end|>\n"
    f"<|im_start|>assistant\n"
)
...
n_imgs = len(image)
replace = "<image1><|vision_start|><|image_pad|><|vision_end|>"
for i in range(2, n_imgs + 1):
    replace += f" <image{i}><|vision_start|><|image_pad|><|vision_end|>"
```

要点：

1. `<image1>` 这个**字面量**就是占位符本身，不是文档里的记号。管线把它写进模板，紧跟其后插入
   `<|vision_start|><|image_pad|><|vision_end|>`（视觉 token 是管线自己补的，**别手写**）。
2. `<image{i}>` 与 `image` 参数的**顺序一一对应**：第一个 `image=` 就是 `<image1>`。
3. 官方 PE（prompt enhancer）的答案契约里也有这个字段：`edit` 任务返回
   `{"rewritten_prompt": "...", "wh_ratio": "", "ratio_follow": "<image1>"}`。
4. 官方 `prompt_rewrite/data/edit_example.jsonl` 的 `multi_portrait` 示例（**正是"两张图两个人同框"**）：

   ```text
   将<image1>中的人物和<image2>中的人物置入一个现代抖音直播间的场景中，生成一张两人并排坐在
   直播桌后共同面向镜头介绍产品的合影照片。保持两位人物的面部特征、发型和服装外观完全不变。
   ```
   `input_images: ["images/1549226_a.png", "images/1549226_b.png"]`

   → 两张图 → `<image1>`/`<image2>`，中文完全可用，而且这就是官方给出的"多主体同框"标准写法。

5. **顺序搞错 = 指代搞错**。`pe_core.py` 的注释原话："Images come first and in order, because the system
   prompt tells the model to address them as `<image1>`, `<image2>`, ... — reordering them silently
   re-points every reference in the rewrite."

用法示例（两个人同框）：

```bash
curl -s -X POST "$BASE/v1/images/generations" \
  -H "Authorization: Bearer $KEY" \
  -F 'image=@person_a.png' -F 'image=@person_b.png' \
  --form-string 'prompt=将<image1>中的人物和<image2>中的人物置入同一个咖啡馆场景，两人相拥。保持面部特征与发型不变。' \
  -F 'num_inference_steps=30' -F 'seed=1234' -o hug.json
```

> **`--form-string` 不是可选项**：`-F 'prompt=...<image1>...'` 会被 curl 解析成"从文件读值"，
> 报 `Couldn't open file "<image1>..."`，必须用 `--form-string`。

两点容易踩的坑：

- **参考图顺序还决定输出宽高比**：管线用 `image[-1]` 算画布，所以"最后一张"的朝向会赢。
  想要竖构图就把竖图放最后，或在请求里显式给 `width`/`height`/`aspect_ratio` 覆盖。
- **`ratio_follow` 只属于官方 PE，不属于这个服务**。PE 是单独的 checkpoint
  （`Qwen-Image-2.1-PE-I2I`），要另起一个 9B VL 模型把用户口语改写成规整 prompt。本服务跑的是
  **原始管线**，没有 PE 那一层，所以"让输出跟随 `<image1>` 的比例"没有对应参数——只有"最后一张赢"
  和"显式指定"两条路。

### 3.4 `POST /v1/images/edits` — 别名（与 3.3 完全等价）

**它和 3.3 是同一个实现**，只是历史上给这条路径起了个"编辑"的名字。新代码统一用
`/v1/images/generations` 即可。留着的理由：老客户端在用，且"编辑"这个词对使用者更直观。

```bash
# 用 3.3 的端点做"编辑"（推荐）
curl -s -X POST "$BASE/v1/images/generations" \
  -H "Authorization: Bearer <你的KEY>" \
  -F 'prompt=Change the background to a sunset beach' -F 'image=@input.png' -o edit.json

# 用老端点，结果一样
curl -s -X POST "$BASE/v1/images/edits" \
  -H "Authorization: Bearer <你的KEY>" \
  -F 'prompt=Change the background to a sunset beach' -F 'image=@input.png' -o edit.json
```

**多参考图合成示例**（两个人拥抱 —— 官方 multi-subject composition）：

```bash
curl -s -X POST "$BASE/v1/images/generations" \
  -H "Authorization: Bearer <你的KEY>" \
  -F 'prompt=These two people are hugging each other warmly, waist up, seaside veranda at golden hour' \
  -F 'image=@person_a.png' -F 'image=@person_b.png' \
  -F 'num_inference_steps=14' -F 'width=1184' -F 'height=1600' \
  -o hug.json
```

本机实测：1184×1600 / 14 步 / **22.1s**（每步 1.35s），两个人的发色与服装分别对应两张参考图。
示例输出：`test-data/remote_outputs/hug_two_people.png`

```bash
curl -s -X POST "http://127.0.0.1:6006/v1/images/edits" \
  -F "prompt=Change the background to a sunset beach" \
  -F "image=@input.png" \
  -F "num_inference_steps=40" \
  -F "seed=42" -o edit.json
```

多参考图示例（3 张）：

```bash
curl -s -X POST "$BASE/v1/images/edits" \
  -F "prompt=These three characters are sitting around a campfire in a forest" \
  -F "image=@ref_0.png" -F "image=@ref_1.png" -F "image=@ref_2.png" \
  -o multi.json
```

响应格式同 3.3。

### 3.5 `POST /v1/jobs` — 异步任务提交

适合会阻塞几十秒到几分钟的请求（批量、列表页预览等）。请求体字段同 3.3，返回 `202`：

```json
{"id": "job_3f9c1b2a4d5e6f70", "status": "queued"}
```

队列满返回 `429 queue full`（默认上限 64，`QWEN_MAX_QUEUE` 可调）。

### 3.6 `GET /v1/jobs/{id}` — 查询

```json
{
  "id": "job_3f9c1b2a4d5e6f70",
  "status": "succeeded",
  "created_at": 1787000000,
  "finished_at": 1787000097,
  "request": {"prompt": "...", "width": 2048, "height": 2048, "num_inference_steps": 40},
  "result": [{"b64_json": "...", "seed": 42, "width": 2048, "height": 2048, "elapsed_s": 96.4}]
}
```

`status` 取值：`queued` → `running` → `succeeded` / `failed` / `canceled`。
失败时带 `error: {code, message}`。

### 3.7 `DELETE /v1/jobs/{id}` — 取消（仅 `queued` 有效）

### 3.8 `GET /v1/jobs?limit=20` — 最近任务列表

### 3.9 `GET /v1/progress` — 真实步进进度（前端进度条的数据源）

进度**不是按时间估的**，是挂在管线的 per-step 回调（`callback_on_step_end`）上，每一步更新一次。

```json
{
  "data": [
    {
      "request_id": "req_abc123",
      "status": "running",          // queued | running | done | error
      "step": 12, "steps_done": 12, "total": 20, "pct": 60.0,
      "elapsed_s": 7.03, "eta_s": 4.1, "per_step_s": 0.514,
      "last_step_s": 0.503, "min_step_s": 0.455, "max_step_s": 0.697,
      "callback_unavailable": false,   // true = 该 diffusers 版本不支持回调，前端改为按步数均分
      "queue_depth": 0,
      "error": null
    }
  ]
}
```

- `GET /v1/progress/{request_id}` 查单个任务。
- 自己发起请求时想轮询某一次，就在请求里带 `request_id`（文生图放 JSON，编辑放 form 字段，或统一用
  `X-Request-Id` 头）；响应也会带 `X-Request-Id` 与 `data[0].timing`。
- `steps_done` 单调递增；`per_step_s` 是**已执行步的平均值**（首步含提示词编码，会比后面慢）。
- 异步任务用 `job_id` 当 `request_id`，`/v1/jobs/{id}` 与 `/v1/progress/{id}` 都能查。

**实测**（1024×1024 / 20 步，4090-48G）：每步稳定在 0.50~0.51s，`eta_s` 从 13.2s 收敛到 0.5s，
`total_s` 10.98s、`prep_s` 0.0s（权重常驻，准备开销可忽略）。

### 3.10 会话（Cookie 登录，控制台用）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/v1/session` | 查当前浏览器有没有有效会话 → `{"authenticated":true/false,"auth_required":…,"expires_in_s":…}` |
| POST | `/v1/session` | body `{"key":"<QWEN_API_KEY>"}` → 200 + `Set-Cookie: qwensess=…; HttpOnly; SameSite=strict; Secure; Max-Age=86400`；key 不对返回 401 |
| DELETE | `/v1/session` | 服务端销毁会话并清 Cookie |

Cookie 名可用环境变量改：`SESSION_COOKIE` 常量（默认 `qwensess`）；有效期 `QWEN_SESSION_HOURS`（默认 24）。
实测（协议层）：

```
GET  /v1/session 未登录      -> 200 {"authenticated":false,"auth_required":true}
POST /v1/session 错 key      -> 401
POST /v1/session 正确 key    -> 200  HttpOnly / SameSite=strict / Secure / Max-Age 全有
带 Cookie  /v1/models        -> 200        不带 Cookie -> 401
带 Cookie  出图              -> 200
DELETE /v1/session           -> 200        退出后带旧 Cookie -> 401（服务端确实销毁了）
```

### 3.11 错误码
| 码 | 含义 |
|---|---|
| 400 | 参数错误（prompt 缺失、size 格式错） |
| 401 | API Key 不匹配 |
| 404 | job / request_id 不存在 |
| 409 | `QWEN_MODE=real` 且当前无 GPU（无卡模式） |
| 429 | 队列满 |
| 503 | 权重目录不存在或没下完 |
| 507 | CUDA OOM：降分辨率/步数，或把 `QWEN_OFFLOAD` 改成 `model` 后重启 |

---

## 4. 上游对接片段

**Python**

```python
import base64, requests

BASE = "https://u39-b3fb-39a640fd.<区域>.seetacloud.com:8443"   # 控制台复制，或隧道地址
r = requests.post(f"{BASE}/v1/images/generations", json={
    "prompt": "sticker of a cute cartoon dragon, flat vector",
    "transparent": True, "aspect_ratio": "1:1", "num_inference_steps": 25, "seed": 1234,
}, timeout=600)
r.raise_for_status()
open("dragon.png", "wb").write(base64.b64decode(r.json()["data"][0]["b64_json"]))
```

**Node / TypeScript**

```ts
const res = await fetch(`${BASE}/v1/images/generations`, {
  method: "POST",
  headers: { "Content-Type": "application/json", ...(KEY ? { Authorization: `Bearer ${KEY}` } : {}) },
  body: JSON.stringify({ prompt, num_inference_steps: 25, seed: 1234 }),
});
const { data } = await res.json();
await fs.writeFile("out.png", Buffer.from(data[0].b64_json, "base64"));
```

**curl 健康探测（做上游存活检查用）**

```bash
curl -sf -m 5 "$BASE/health" | jq -e '.status == "ok" and .checkpoint.present == true'
```

---

## 5. 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `QWEN_MODEL_DIR` | `/root/autodl-tmp/Qwen-Image-2.1` | 权重目录 |
| `QWEN_PORT` | `6006` | 监听端口（6006/6008 是 AutoDL 映射口） |
| `QWEN_MODE` | `auto` | `auto` / `real` / `mock` |
| `QWEN_OFFLOAD` | `none` | `none` / `model` / `sequential` / `cpu`；48G 单卡常驻用 `none`，OOM 再降级 |
| `QWEN_PRELOAD` | `1` | 启动即加载权重并预热，首请求不用等 2~3 分钟 |
| `QWEN_SAFETY_GIB` | `2.0` | 显存预检保留余量 |
| `QWEN_LATENT_GIB_2K` | `8.0` | 2048² 的 latent/attention 经验占用，用于预检
| `QWEN_TORCH_DTYPE` | `bfloat16` | 或 `float16` |
| `QWEN_TILE_VAE` | `0`（`serve.sh` 里设成 1） | `1` 开启 VAE 分块解码省显存；**2048² 出图必须开** |
| `QWEN_API_KEY` | `<你的KEY>` | 主 key；所有 key 都为空则关闭鉴权（公网入口会变成任何人可用） |
| `QWEN_API_KEYS` | （可留空） | 额外 key，逗号分隔，**同样有效**（换 key 过渡 / 短口令） |
| `QWEN_UI_KEY` | `auto` | `inject`（把 key 填进页面，仅自己用）/ `auto`（不注入，走 Cookie 会话）/ `off` |
| `QWEN_SESSION_HOURS` | `24` | 会话 Cookie 有效期（小时） |
| `QWEN_COOKIE_SECURE` | `1` | Cookie 是否带 `Secure`（公网是 https 保持 1；纯 http 调试设 0） |
| `QWEN_MAX_QUEUE` | `64` | 异步队列上限 |

---

## 6. 本机调试

**JupyterLab 控制台（推荐，点鼠标就行）**

实例上放了笔记本 `/root/qwen-image-2.1/service/ui/Qwen-Image-2.1-控制台.ipynb`，
JupyterLab 左侧文件树进 `qwen-image-2.1/service/ui/` 打开它。里面 9 节：启动/重启服务、
打开 WebUI、端口与入口一览、输出目录预览、直接调 API 出图、实时进度、上传图片、
**API 速查**、常见问题。按钮不灵的 JupyterLab 版本，改用「把 `ACTION` 改成 start」那一格，
效果一样。

笔记本生成器：`python tools/make_notebook.py`（改内容改这个，别手改 .ipynb）；
校验：`python tools/check_notebook.py`。

> JupyterLab 的 `base_url` 是 `/jupyter/`，所以反代其它服务的规律是
> `/jupyter/proxy/<端口>/`，例如 WebUI 走 `/jupyter/proxy/6006/`；文件用 `/jupyter/files/<路径>`。

**命令行客户端 `service/client.py`**

```bash
# 先开隧道（见第 1 节；或直接对公网入口用 --base-url）
ssh -p <端口> -L 16006:127.0.0.1:6006 root@connect.west?.seetacloud.com -N

python service/client.py health --base-url http://127.0.0.1:16006
python service/client.py t2i "a capybara reading a book by candlelight" \
       --base-url http://127.0.0.1:16006 -o out.png
python service/client.py t2i "cute dragon sticker" --transparent \
       --aspect-ratio 1:1 --steps 25 -o dragon.png
python service/client.py edit input.png "make the sky sunset" -o edited.png
python service/client.py job "panorama of a mountain lake at dawn" -o pano.png
```

OpenAPI 交互文档（服务开着时）：`http://127.0.0.1:6006/docs?key=<你的KEY>`。
