# 生成图里的元数据

> 从 2026-09-26 起，服务生成的每张图都把**完整生成信息写进 PNG 自己**。
> 拿到一张图就能知道它是谁、用什么参数生成的、怎么复现。
> 读取工具：`python tools/read_metadata.py 图.png [--json] [--verify]`

## 现在有没有？（历史图）

**2026-09-26 之前生成的图没有任何元数据** —— 实测过 8 张旧图，
`info keys` 全空、EXIF 0 个 tag。PIL 默认不写任何生成信息，
`QwenImage21PipelineOutput` 也只有 `images`，服务端此前也没补。
**元数据从加上之后的新图开始才有**，旧图无法追溯补回（信息已经丢了）。

## 放在哪

PNG 的 **iTXt 文本块**，键名 `qwen_image_21`，值是 UTF-8 的 JSON。

- 选 iTXt 而不是 tEXt：tEXt 是 latin-1，中文 prompt 会截断或报错。iTXt 是 UTF-8。
- 同时写一份纯文本键 `parameters`（`Steps: / Seed: / Size: / Model hash:` 那套格式），
  兼容 A1111 / ComfyUI 生态里按惯例读它的工具。
- 用任意看图软件都能看；`exiftool`、`pngcheck`、Python 的 `im.info['qwen_image_21']` 都能取。

## 前向兼容（加字段不会破坏老读取方）

载荷是**带版本号的 JSON 对象**：

```json
{
  "schema": "qwen-image-2.1/generation",
  "schema_version": 1,
  ...
}
```

约定：**读取方遇到不认识的字段一律忽略**，服务端以后加字段只递增需要时再改
`schema_version`，老工具不会报错。`tools/read_metadata.py` 会在末尾打印
"本工具不认识的字段"，而不是崩掉 —— 这一点有专门的测试覆盖
（往元数据里塞一个假字段，验证还能正常读）。

## 字段一览

| 字段 | 内容 |
|---|---|
| `schema` / `schema_version` | 载荷格式标识与版本 |
| `generator.name` / `.version` / `.created_at` | 生成器与其版本、生成时间 |
| `model.model` | `Qwen-Image-2.1` |
| `model.weights_sha256` | **模型权重的全量 SHA-256**（29 个文件 / 33.1 GB 一次算完并缓存） |
| `model.weights_sha256_source` | `computed`(刚算的) / `cache`(读缓存) |
| `model.state` | `ok`=全量 hash 可用；`partial`=还在后台算，只有 `light_digest` |
| `model.light_digest` | 每文件路径+大小+前后 64 KB 的采样摘要（毫秒级，做变更检测） |
| `model.signature` | 文件数 / 总字节 / 最新 mtime |
| `model.model_dir` | 权重目录绝对路径 |
| `model.dtype` / `tile_vae` / `offload` | 推理配置（bfloat16 / true / none） |
| `request.prompt` | **提示词原文**（含 `<image1>` 之类的引用） |
| `request.negative_prompt` | 负面提示词 |
| `request.width` / `.height` | 实际输出尺寸 |
| `request.aspect_ratio` / `.output_resolution` | 档位与像素预算（用了才有） |
| `request.num_inference_steps` | 步数 |
| `request.seed` | **本次实际用的种子**（留空时是服务端掷的那个） |
| `request.seed_given` | `false` = 自动掷的 |
| `request.true_cfg_scale` / `.guidance_scale` | CFG 设置 |
| `request.transparent` / `.output_format` | 透明通道、输出格式 |
| `request.request_id` | 这次请求的 id（和 `/v1/progress` 对得上） |
| `inputs[]` | 每张参考图：`index`（对应 prompt 里的 `<imageN>`）、`sha256`、尺寸、`name` |
| `output.content_sha256` | **像素内容指纹**（认图用，见下） |
| `output.width` / `.height` / `.mode` / `.index` / `.count` | 这张图本身 |
| `timing` | 总耗时、每步耗时、准备/解码/编码分段耗时 |
| `environment` | torch / CUDA 版本、GPU 型号、Python 版本 |
| `anatomy_check` | 开了审图才有：是否通过、重试次数、每轮判定 |

## 两个哈希，别搞混（重要）

| 哈希 | 是什么 | 存在哪 | 用途 |
|---|---|---|---|
| `output.content_sha256` | **解码后像素**的 SHA-256（统一 RGBA + 尺寸拌入） | 写在 PNG 里 | 判断"是不是同一张图" |
| `output.png_sha256` | **最终 PNG 文件字节**的 SHA-256 | 只在 **API 响应**里 | 判断"文件有没有被改过" |

为什么要这么分：

1. **文件自身的哈希不可能存在文件里** —— 那是自指（写进去就改变了哈希）。
   所以 PNG 内的 `png_sha256` 恒为空，它只随响应/清单发出。
2. **不能拿 PNG 字节当内容指纹** —— PNG 编码结果依赖 Pillow/zlib 版本，
   同一张图在两台机器上写出的字节不同（实测：本地与服务端就对不上）。
   像素是确定的，所以内容指纹算像素。

校验方式：

```bash
# 内容校验（跨机器有效）：用同一套算法重算像素指纹
python tools/read_metadata.py 图.png --verify
```

```python
# 自己算也行，等价于服务端的做法
from PIL import Image
import hashlib
im = Image.open("图.png"); im.load()
im = im if im.mode == "RGBA" else im.convert("RGBA")
h = hashlib.sha256()
h.update(f"RGBA\0{im.width}\0{im.height}\0".encode())
h.update(im.tobytes())
print(h.hexdigest())          # == metadata["output"]["content_sha256"]
```

## 怎么复现一张图

拿元数据里的这几项原样再请求一次即可（同一台机器 + 同一份权重）：

```bash
python tools/read_metadata.py 图.png --json | python -c "
import json,sys
m=json.load(sys.stdin)['request']
print(json.dumps({'prompt':m['prompt'],'negative_prompt':m.get('negative_prompt'),
 'width':m['width'],'height':m['height'],'num_inference_steps':m['num_inference_steps'],
 'seed':m['seed']}, ensure_ascii=False))"
```

注意：**换了权重就不是同一张图**。先对 `model.weights_sha256` 确认权重一致。

## 体积开销

元数据是压缩块，实际开销很小（实测）：

| 尺寸 | 开销 |
|---|---|
| 512×512 | +1.6 KB |
| 768×1024 | +1.7 KB |

相对 1 MB 级的图可以忽略。

## 关掉它

```bash
export QWEN_PNG_METADATA=none    # 图里不留 prompt（分享给别人时可用）
```

默认为 `json`（写元数据）。关掉后响应里也不再带 `metadata` 字段。

## API 响应里的精简版

不想解 PNG 也能从响应里拿：

```json
"metadata": {
  "schema": "qwen-image-2.1/generation", "schema_version": 1,
  "png_chunk": "qwen_image_21",
  "model": "Qwen-Image-2.1", "model_hash": "7004a46c088b0ab1", "model_hash_state": "ok",
  "seed": 4242, "steps": 10, "size": "768x1024",
  "prompt": "一只戴红围巾的白猫坐在窗台上，午后阳光",
  "inputs": [], "content_sha256": "…", "png_sha256": "…"
}
```

`/health` 里也能看到当前的模型指纹：

```bash
curl -s localhost:6006/health | python -c "import json,sys; print(json.load(sys.stdin)['checkpoint']['fingerprint'])"
```
