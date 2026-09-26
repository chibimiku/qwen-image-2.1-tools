# 分辨率与尺寸：机制、如何选最优解

> 这份是从**代码 + 实测**推出来的，不是猜的。每一条都标了出处（文件行号 / 实测命令）。
> 结论先给：**`output_resolution` 不是"输出边长"，它是"像素预算杠杆"，
> 且只该取到与输出边长相当为止 —— 再大就是白花钱。**

## 一、先回答"官方是不是只允许 1024 / 1280"

**不是。官方没有档位枚举，也没有任何校验。**

`docs/upstream/diffusers-pipeline_qwenimage21.py`：

```python
L527:  output_resolution: int = 1024,          # 只有默认值
L579:  output_resolution (`int`, *optional*, defaults to 1024):
L580:      Target side length used to derive `height`/`width` and to resize condition images.
```

- 全仓库（README / 模型卡 / ModelScope / 博客 / LICENSE）搜 `output_resolution`，
  除了管线签名与这条 docstring，**没有任何"可选值"说法**。
- `check_inputs()`（L389-407）只检查 `height/width` 能否被 `vae_scale_factor*2 = 32` 整除，
  而且**只是 warning + 自动调整**，不报错；对 `output_resolution` 本身**完全不校验**。
- 官方明确推荐的尺寸表是 **`aspect_ratio`** 那 7 个 2K 档位（README「Supported Aspect Ratios」），
  和 `output_resolution` 是**两个不同的参数**，别混。

我们 UI 里的 `1024 / 1280` 只是当初给的两个预设，**不是官方限定**。
接口层面任何正整数都能传。

## 二、它到底做了什么：两个作用

### 作用 1：没给宽高时，决定输出尺寸（像素预算）

管线 L621-627：

```python
calculated_width, calculated_height, _ = calculate_dimensions(
    output_resolution * output_resolution, image[-1].size[0] / image[-1].size[1])
height = height or calculated_height      # ← 给了宽高，下面这行直接作废
width  = width  or calculated_width
```

`calculate_dimensions`（L149-156）就是：

```python
width  = sqrt(target_area * ratio);  width  = round(width / 32) * 32
height = width_未取整 / ratio;        height = round(height / 32) * 32
```

所以 `output_resolution` 的**平方**是像素预算，比例来自最后一张参考图。
**给了 `width`/`height` 时，这个作用被完全忽略。**

### 作用 2：决定参考图被缩到多大再喂给模型（给了宽高也照样生效）

管线 L648-663 —— 注意注释"one resize feeds both"：

```python
# 1. Preprocess condition images: one resize feeds both the text encoder and the VAE.
for img in image:
    ...
    input_width, input_height, _ = calculate_dimensions(
        output_resolution * output_resolution, image_width / image_height)
    input_images.append(self.image_processor.resize(img, width=input_width, height=input_height))   # → 视觉编码器
    vae_images.append(self.image_processor.preprocess(img, width=input_width, height=input_height)...)  # → VAE
```

**同一份缩放结果，既给 Qwen3-VL 视觉编码器，也给 VAE。**
所以 `output_resolution` 同时决定了：模型"看到"的参考图清晰度，以及条件 latent 的 token 数。

这就是为什么上一轮实测里"宽高固定 512×512，把 `output_resolution` 从 1024 改到 1280，
输出 md5 也变了"—— 边长一样，但参考图看到的细节不同。

> 附带一条：RGBA 参考图会被**合成到白底**再给视觉编码器（L266-271），
> 但 VAE 仍然读 4 个通道。透明参考图的实际观感按白底算。

## 三、算力与显存为什么对分辨率这么敏感（token 经济账）

### 一条 token 管 16×16 像素

管线 L199-201 官方原话：

```python
# The VAE compresses 16x spatially and the transformer consumes latents unpatched,
# so one token covers a 16x16 pixel tile.
self.vae_scale_factor = 16
```

"unpatched" 是关键：**2.1 不做 patch 打包，latent 是纯空间展平**（L410-412 `_pack_latents`）。
于是：

```
token 数 = 像素数 / 256
```

### 条件图 latent 会被**拼到去噪序列里**，不是只当缓存

管线 L766-768：

```python
latent_model_input = latents
if input_images_latents is not None:
    latent_model_input = torch.cat([input_images_latents, latents], dim=1)
```

去噪每一步的序列 = **条件图 token + 噪声 token**。（`use_kv_cache` 缓存的是文本/条件 K-V，
但条件 latent 仍然在这个序列里参与。）

### 合起来

设 `R = output_resolution`，`N` = 参考图张数，参考图比例与输出一致：

| 量 | 表达式 | R=1024, N=1 | R=1024, N=2 | R=2048, N=1 |
|---|---|---|---|---|
| 单图 token | R²/256 | ~4.1k | ~4.1k | ~16.4k |
| 去噪序列总长 | (N+1)·R²/256 | ~8.2k | ~12.3k | ~32.8k |
| 注意力成本 ∝ 长度² | — | 67M | 151M | 1074M |

**这就是为什么编辑模式的显存曲线那么陡**（我们服务端用 `3.65 G/MP²` 标定，
比文生图的 `0.5 G/MP²` 陡 7 倍）：条件图让序列变长，而注意力是平方的。
也就解释了"加一张参考图"和"分辨率翻倍"为什么都那么贵。

**再往下推一层**：`R` 和输出边长在"跟随模式"下是同一个量，所以跟随模式下
`R` 翻倍 = 输出边长翻倍 = token 数 ×4 = 注意力成本 ×16。这也是为什么服务端
在跟随模式下把 `R` 当唯一旋钮。

### 有没有硬上界？

只找到一条**理论**上界，实际够不着：RoPE 频率表是预建的
（`diffusers-transformer_qwenimage21.py` L666-671）：

```python
pos_index = torch.arange(8192)
neg_index = torch.arange(1024).flip(0) * -1 - 1
```

空间索引范围是 `[-1024, 8191]`，而 latent 边长上限 = `8192 + 1024 = 9216`
→ ×16 = **147456 像素边长**。没有任何实际图像会碰到它。

所以**真正的上界是显存，不是代码**。

## 四、怎么选最优解（按你的参考图）

先记住 UI 里三个尺寸控件的关系（见 `docs/API.md` 3.9.4 与界面 tooltip）：

```
跟随参考图 ✔ → 只发 output_resolution：它同时定输出尺寸与参考图清晰度
跟随参考图 ✘ → 选档位 / 手填宽高定输出尺寸；output_resolution 只管参考图清晰度
```

### ⚠️ 先看一条反直觉的实测：调大**不保证更好，可能更差**

`docs/MEASUREMENTS.md` §3.1 的实测（单参考图做姿势/表情编辑，1696×2528 参考图）：

| output_resolution | 实际输出 | 耗时 | 人脸保真度 |
|---|---|---|---|
| 1024（默认） | 832×1248 | 24.5 s | 基准（漂移 0.172） |
| 1280 | 1056×1568 | 50.8 s | **更差**（漂移 0.203） |

**耗时翻倍，一致性反而下降。** 所以"调大 = 更好"是错的，得分任务看（下一节）。

### 判据：`min(参考图边长, 输出边长)` —— 超过这个数就是浪费

机制上（作用 2）参考图被缩到 `output_resolution` 的预算，而输出的细节上限由输出边长决定：

- 参考图缩到比输出还大 → 模型看到的细节超过它能画出来的 → **白花算力**。
- 参考图缩得比输出小 → 细节被压掉 → 对"照着参考图重建"这类任务不利。

但**"细节更多"不等于"结果更好"**：这个模型每次编辑都会重绘整张图（含脸），
所以参考图看得更清楚并不会让它更守原图 —— 上面那条实测就是这么来的。

### 按任务分

| 任务 | 建议 | 依据 |
|---|---|---|
| **局部编辑**（换背景/换衣服/改风格/改姿势），单张参考图 | **1024**（默认），别调大 | §3.1 实测：1280 耗时翻倍且人脸漂移更大 |
| **照着参考图重建**（如三视图/立绘 → 还原角色），细节（花纹、文字、服饰）重要 | 参考图长边 ≥ 2048 时可试 **1280** | 机制上参考图 token 更多、细节保留更好；**但未做保真度实测**，属合理推断 |
| 参考图本来就小（长边 ≤ 1024） | **1024** | 再大没有细节可给，只会插值放大 |
| 只想要特定尺寸/比例 | 取消跟随，选档位或手填宽高 | `output_resolution` 此时不影响输出边长 |

**结论：默认就用 1024。** 只有当"参考图很清晰 + 任务靠细节认人/认物"时才试 1280，
并且**自己比一下结果**再决定 —— 别默认认为调大就好。

### 实测锚点（本机，48G 全常驻）

来源：`docs/MEASUREMENTS.md`。

| 配置 | 每步耗时 | 备注 |
|---|---|---|
| 编辑 512×512，outres 1024 | ~0.5s | — |
| 编辑 1024² 附近（1.05MP） | ~0.6s | 1184×1600/14 步 ≈1.35 s/步 |
| 编辑 1.92MP（1184×1600） | ~1.4s | **本机编辑红线** |
| 编辑 2.17MP（1280×1696） | — | **OOM** |
| outres 1024 → 1280（同任务） | 24.5s → 50.8s | 总耗时翻倍 |

> `output_resolution` 的档位变化不是线性的：跟随模式下它同时改输出边长和参考图边长，
> 两者都进同一个去噪序列（见第三节）。所以别只看"边长只涨 1.56 倍"。

### 一句话决策

1. **先用「跟随参考图」**（默认勾选）+ `output_resolution` **保持默认**。
2. 参考图很清晰、任务需要认细节（还原角色/花纹/文字）→ 试 **1280**，并对比结果。
3. 局部编辑（换背景/换风格）→ **1024**，调大是白花一倍时间还未必更好。
4. 想要特定尺寸/比例 → 取消跟随，选档位或手填宽高；这时 `output_resolution`
   就只管参考图清晰度了（超显存服务端会按同比例自动缩，并在 `metadata.size_note` 里说明）。

## 五、容易踩的坑

| 坑 | 说明 |
|---|---|
| **以为调大就更好** | 实测反例：outres 1024→1280，耗时翻倍、人脸漂移 **变大**（0.172→0.203）。按任务选，别默认调大 |
| 以为 `output_resolution` 是输出边长 | 给了宽高时它**不影响输出尺寸**，但仍影响结果（作用 2） |
| 以为 1024/1280 是官方档位 | 官方只给默认值 1024，没有任何枚举或校验 |
| 宽高不是 32 的倍数 | 管线只 warning + 自动调整；我们服务端统一按 32 对齐 |
| 以为给宽高后 `output_resolution` 就无关了 | 错。参考图清晰度仍由它决定，实测 md5 会变 |
| 以为参考图会被原样送进去 | 会被缩到 `output_resolution` 的预算（`calculate_dimensions`） |
| 透明参考图 | 视觉编码器看的是**白底合成**后的版本；VAE 仍读 4 通道 |

## 六、复核用

```bash
# 各档位在本机实际能跑多大（服务端按实测基线算）
curl -s "$BASE/v1/fit?all_ratios=true&steps=30" -H "Authorization: Bearer $KEY"

# 验证 output_resolution 的两个作用（remote/scripts/_outres_probe.py）
#   宽高固定、只改 outres → md5 变（作用 2）
#   只给 outres → 输出尺寸随之变（作用 1）
```

代码位置索引（都在 `docs/upstream/`）。这些行号用 `python tools/check_doc_refs.py docs/RESOLUTION.md` 自查：

| 内容 | 位置 |
|---|---|
| `calculate_dimensions` 公式 | `diffusers-pipeline_qwenimage21.py:149` |
| token = 16×16 像素 / latents 未打包 | `diffusers-pipeline_qwenimage21.py:199` |
| RGBA 合成白底（仅视觉编码器） | `diffusers-pipeline_qwenimage21.py:266` |
| `check_inputs` 只查 32 整除 | `diffusers-pipeline_qwenimage21.py:389` |
| `_pack_latents` 纯空间展平 | `diffusers-pipeline_qwenimage21.py:410` |
| `output_resolution` 默认值 | `diffusers-pipeline_qwenimage21.py:527` |
| 尺寸优先级（宽高抢先） | `diffusers-pipeline_qwenimage21.py:621` |
| `height = height or calculated_height` | `diffusers-pipeline_qwenimage21.py:624` |
| 一次 resize 喂两路 + 参考图缩放 | `diffusers-pipeline_qwenimage21.py:648` |
| 参考图按预算缩放（calculate_dimensions） | `diffusers-pipeline_qwenimage21.py:656` |
| 条件 latent 拼进去噪序列 | `diffusers-pipeline_qwenimage21.py:766` |
| `torch.cat([条件, 噪声])` | `diffusers-pipeline_qwenimage21.py:768` |
| RoPE 预建频率表（理论上界） | `diffusers-transformer_qwenimage21.py:666` |

维护提示：上游源码更新后行号会漂移，跑一次自查脚本就能发现 —— 失败时它会打印该行实际内容，
方便定位新行号。
