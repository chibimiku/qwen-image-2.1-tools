# WebUI 说明文案与参数选项核查

> 核查对象：`service/ui/index.html` + `service/server.py`
> 时间：2026-09-26　方法：逐项对着服务端解析代码与官方源码/README 核对，不靠印象
> 结论：**7 项正确、4 项已修、1 项已知限制**

## 一、参数选项核查

| # | UI 选项 | UI 写的默认/范围 | 服务端实际 | 判定 |
|---|---|---|---|---|
| 1 | `num_inference_steps` | 滑块 4~60，默认 **30** | multipart `int(g("num_inference_steps", 40))` → 服务端默认 40 | ✅ 正确（UI 自己给 30，官方默认 40，两者都合理） |
| 2 | `aspect_ratio` | 7 档：1:1 2048² / 4:3 2400×1792 / 3:4 1792×2400 / 3:2 2528×1696 / 2:3 1696×2528 / 16:9 2752×1536 / 9:16 1536×2752 | `ASPECT_RATIOS` 同名同值，命中即覆盖 width/height | ✅ 正确，与官方 README「Supported Aspect Ratios」逐字一致 |
| 3 | `width` / `height` | 默认 1024×1024，step 16 | `_resolve_size`：两边都缺 → 2048² | ✅ 正确（UI 在 t2i 下总会给显式值） |
| 4 | `seed` | 留空或**负数**=随机；出图后不回填输入框，点历史缩略图才填回该图 seed | `_norm_seed()`：`None` / `""` / `<0` 一律 → `None`（服务端自己掷） | ✅ 正确（负数以前会被原样送进 generator，见 §2.4） |
| 5 | `transparent` | 复选 | `str(g("transparent","")).lower() in ("1","true","on","yes")` | ✅ 正确（UI 传 `true`） |
| 6 | `output_resolution` | 仅编辑模式显示，1024 / 1280 | 有参考图时决定像素预算；**给了宽高时仍决定参考图被缩到多大**（官方 docstring：derive height/width **and to resize condition images**） | ✅ 正确；语义详见 [RESOLUTION.md](RESOLUTION.md)，文案已改成两点式说明 |
| 7 | `negative_prompt` | 仅文生图模式显示 | 原来只在 JSON 分支解析 | ⚠️ **已修**（见下） |
| 8 | `guidance_scale` | UI 未暴露 | 原来只在 JSON 分支解析 | ⚠️ **已修**（见下） |
| 9 | `size` | UI 未暴露 | `_resolve_size` 支持 `"2048x2048"` | ✅ 一致（UI 用档位/宽高即可） |

## 二、已修的五处

### 2.1 multipart 会静默丢掉 `negative_prompt` / `guidance_scale`

`_parse_gen_request()` 的两个分支不对称：JSON 分支读了这两个字段，multipart 分支没读。
UI 的负面提示词框只在文生图模式出现，而文生图模式恰好带着文件时不发 multipart，
所以**眼下撞不上**；但任何用 multipart 调 API 的人传了都会静默失效 —— 属于埋雷，已修。

```python
# server.py multipart 分支新增
neg = g("negative_prompt")
gscale = float(g("guidance_scale")) if g("guidance_scale") is not None else None
```

### 2.2 `guidance_scale` 根本不存在 —— 传了就 500（本轮真实测出来的）

`docs/API.md` 里一直写着「`guidance_scale` 官方推荐 CFG=1 时可直接给 1.0」，
服务端也老老实实往管线 kwargs 里塞。但远端的管线签名里**没有这个参数**：

```text
params: 23 → prompt, image, negative_prompt, true_cfg_scale, height, width,
             num_inference_steps, sigmas, num_images_per_prompt, generator, latents,
             prompt_embeds, prompt_embeds_mask, negative_prompt_embeds,
             negative_prompt_embeds_mask, output_type, return_dict, attention_kwargs,
             callback_on_step_end, callback_on_step_end_tensor_inputs,
             output_resolution, use_kv_cache
has guidance_scale : False
has true_cfg_scale : True
```

所以这是**一条一直坏着的文档 + 一条一直 500 的代码路径**（JSON 路径同样中招，
只是从来没人真的传过）。修法两层：

1. `guidance_scale` 映射到 `true_cfg_scale`，两个名字都收（multipart 与 JSON 都行）。
2. **门口拦截**：调用前用 `inspect.signature(pipe.__call__)` 取真实参数表，
   kwargs 里不认识的一律丢弃并打日志。以后再有类似的名字对不上，是丢参数 + 一行警告，
   而不是一整个 500。
### 2.3 只给一边尺寸（只填宽或只填高）会半截传下去

`width=1200, height=(空)` 这种请求，原来 `width and height` 为假 → 走推导分支补成一对；
但 `width=1200` 且**有参考图**时 `explicit=True`，就带着 `height=None` 进了预检和管线，
在离现场很远的地方炸成 `TypeError: unsupported operand type(s) for *: 'NoneType'`。已修：

```python
if bool(width) != bool(height):
    ratio = (images_in[-1].size[0] / images_in[-1].size[1]) if images_in else 1.0
    if width:  raw_w, raw_h = float(width), float(width) / ratio
    else:      raw_w, raw_h = float(height) * ratio, float(height)
    width  = round(raw_w / 32) * 32     # 补成完整一对并 32 对齐
    height = round(raw_h / 32) * 32
```

回归测试：`tools/check_server_size.py`（语法 + 官方尺寸公式 9 例 + 补全逻辑 8 例）。

### 2.4 seed：负数当种子用 + 出图后自动回填（两个都是逻辑 bug）

**一、负数被当成真种子。** multipart 分支是 `int(g("seed"))`，JSON 分支直接 `b.get("seed")`，
`seed=-5` 会原样进 `torch.Generator().manual_seed(-5)` —— 生成是能跑，但响应里回的是一个
**假的可复现参数**：用户照抄 `-5` 并不能复现同一张图。现在两条分支共用：

```python
def _norm_seed(value):        # None / "" / 负数 → None（= 服务端自己掷一个真随机种子）
```

实测（实例上真跑，见 `remote/scripts/_verify_ui_seed_fix.sh`）：

| 请求 | 响应 |
|---|---|
| 不传 seed | `seed=854362748, seed_given=false` ✅ |
| `seed=-5` / `seed=-1` | 随机，`seed_given=false` ✅ |
| `seed=0` | `seed=0, seed_given=true` ✅（0 是合法种子，不是"没给"） |
| `seed=4242` | `seed=4242, seed_given=true` ✅ |
| 编辑（multipart）`seed=-7` / `seed=7` | 随机 / `seed=7` ✅ |

**二、出图后把随机种子写回输入框。** 上一轮为了"想复现时有个值可抄"做了自动回填，
副作用是**留空从此变成固定**：用户不动它，下一张就是上一张的复刻。现在：

- 出图**不回填**，输入框保持用户自己的值（留空就一直随机）；
- 实际种子照旧显示在右上角 `seed` 卡片和右侧历史里；
- 想复现某一张 → **点历史里的缩略图**，那一瞬间才把该图的 seed 填进输入框（并写一行日志）；
- 「复用当前参数」按钮仍会带上 seed，日志里注明"想重新随机就把 seed 清空"。

回归测试：`python tools/webui_logic_check.py` —— 它用 DOM 桩子在 Node 里**真跑页面脚本**
（本沙箱不许起浏览器），断言 `seed=""` / `"-5"` → `params().seed === undefined`、
`showHist(0)` → 输入框变成该图 seed、再清空又回到随机；同时检查 CSS 级联里
`.chk` 最终 `display` 必须是 `flex`（见 §2.5）。

### 2.5 选项对钩后面的说明文字掉到下一行（纯 CSS 层叠事故）

`.chk` 本来是 `display:flex`（对钩与说明文字同一行），后面又补了一条 `.chk{display:block}`；
两条同权重，后写的赢 —— 于是 `label` 变回块级元素（全局 `label{display:block}`），
文字被挤到对钩下面另起一行。修法：删掉那条覆盖，并把 `label` 明确声明成 flex 项
（`flex:1 1 auto; min-width:0`），长文本在自身宽度内折行而不是整体换行。

## 三、文案修正（已完成）

`输出分辨率 output_resolution` 的 label 原先写「仅编辑模式，默认 1024→输出 832×1248」。

- **"832×1248" 是错的当示例看**：输出尺寸 = 1024² 像素预算按**参考图比例**摊开，
  所以 832×1248 只对应"参考图是 2:3"这一种情况。换张 1:1 的参考图，同样的默认值出 1024×1024。
- **"仅编辑模式" 对 UI 成立、对后端不成立**：管线签名里 `output_resolution` 与模式无关
  （"`output_resolution`² 是像素预算，比例取 `image[-1]`；显式给 width/height 则直接用你给的值"），
  文生图时它同样有效。只是 UI 把这个控件收在编辑模式下（文生图用档位/宽高更直观），所以对用户没有歧义。
- **还漏了第二个作用**：它同时决定**参考图被缩到多大再喂给模型**
  （官方 docstring：`... and to resize condition images`），所以给了宽高之后它**仍然影响结果**。

**已改**：label 换成两点式说明（哪一步决定尺寸、哪一步影响清晰度）+ 一条实测警告
（不是越大越好，见 [RESOLUTION.md](RESOLUTION.md)）。

## 四、验证过、确认不用改的文案

| 文案 | 核对结果 |
|---|---|
| 「输出比例默认跟随**最后一张**参考图」 | ✅ 管线 `_derive_size` 用 `images[-1].size` 定比例，实测 A+B → 1024²、B+A → 896×1184 |
| 「编辑输出上限约 1.92MP（1184×1600）」 | ✅ 实测 1.92MP 通过、2.17MP（1280×1696）OOM |
| 「2048² 每步约 2.6 秒（约 1024² 的 5 倍）」 | ✅ 实测 2048²/40 步 ≈115s ≈2.9s/步；1024²/20 步 ≈11s ≈0.55s/步 |
| 「<15 步只适合试构图，画面会糊」 | ✅ 与矩阵测试观察一致 |
| 「透明是原生生成的 alpha，不是抠图」 | ✅ 模型是 64 通道 RGBA VAE，官方 README「Native Transparency」 |
| 「最多 10 张参考图」 | ✅ 官方 README「up to 10 reference images」，UI 也卡在 10 |
| Tab 区别 tooltip（同一管线、`image` 可选） | ✅ 与本仓库 API.md 3.3 节、管线签名一致 |

## 五、已知限制（写在这里备查，不在本次改动范围）

1. **参考图不能拖拽排序**。tooltip 已如实说明「想换顺序就先删掉再按新顺序重新添加」。
   顺序同时影响 `<imageN>` 编号和输出比例，所以这个限制值得后续补。
2. **`negative_prompt` 在编辑模式不可见**。后端已支持（本次修好 multipart），UI 没开。
   想用可以先在文生图模式填好再切过去（表单记忆会保留），或直接调 API。
3. **没有速率限制/配额**。`QWEN_API_KEY` 是唯一闸门，公网入口一旦泄漏 key 等于送 GPU。
4. **`ratio_follow` 类参数不存在**。那属于官方 PE（另一个 checkpoint），本服务跑原始管线。

## 六、复核命令

```bash
node tools/check_ui_js.js service/ui/index.html   # UI 内联 JS 语法 + 关键符号自检
python tools/check_server_size.py                 # server.py 语法 + 尺寸公式/补全算术
python tools/check_size_formula.py                # 官方尺寸公式 7/7 对照
python tools/scan_secrets.py                      # 提交前凭据扫描
```
