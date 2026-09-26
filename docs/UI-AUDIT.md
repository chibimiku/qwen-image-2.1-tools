# WebUI 说明文案与参数选项核查

> 核查对象：`service/ui/index.html` + `service/server.py`
> 时间：2026-09-26　方法：逐项对着服务端解析代码与官方源码/README 核对，不靠印象
> 结论：**7 项正确、2 项已修、1 项已知限制**

## 一、参数选项核查

| # | UI 选项 | UI 写的默认/范围 | 服务端实际 | 判定 |
|---|---|---|---|---|
| 1 | `num_inference_steps` | 滑块 4~60，默认 **30** | multipart `int(g("num_inference_steps", 40))` → 服务端默认 40 | ✅ 正确（UI 自己给 30，官方默认 40，两者都合理） |
| 2 | `aspect_ratio` | 7 档：1:1 2048² / 4:3 2400×1792 / 3:4 1792×2400 / 3:2 2528×1696 / 2:3 1696×2528 / 16:9 2752×1536 / 9:16 1536×2752 | `ASPECT_RATIOS` 同名同值，命中即覆盖 width/height | ✅ 正确，与官方 README「Supported Aspect Ratios」逐字一致 |
| 3 | `width` / `height` | 默认 1024×1024，step 16 | `_resolve_size`：两边都缺 → 2048² | ✅ 正确（UI 在 t2i 下总会给显式值） |
| 4 | `seed` | 留空=随机 | `int(g("seed")) if ... is not None else None` | ✅ 正确（空串→None→随机） |
| 5 | `transparent` | 复选 | `str(g("transparent","")).lower() in ("1","true","on","yes")` | ✅ 正确（UI 传 `true`） |
| 6 | `output_resolution` | 仅编辑模式显示，1024 / 1280 | 有参考图时决定像素预算，服务端自己算完再把显式宽高传下去 | ✅ 正确，但**说明文案不精确**（见下） |
| 7 | `negative_prompt` | 仅文生图模式显示 | 原来只在 JSON 分支解析 | ⚠️ **已修**（见下） |
| 8 | `guidance_scale` | UI 未暴露 | 原来只在 JSON 分支解析 | ⚠️ **已修**（见下） |
| 9 | `size` | UI 未暴露 | `_resolve_size` 支持 `"2048x2048"` | ✅ 一致（UI 用档位/宽高即可） |

## 二、已修的两处

### 2.1 multipart 会静默丢掉 `negative_prompt` / `guidance_scale`

`_parse_gen_request()` 的两个分支不对称：JSON 分支读了这两个字段，multipart 分支没读。
UI 的负面提示词框只在文生图模式出现，而文生图模式恰好带着文件时不发 multipart，
所以**眼下撞不上**；但任何用 multipart 调 API 的人传了都会静默失效 —— 属于埋雷，已修。

```python
# server.py multipart 分支新增
neg = g("negative_prompt")
gscale = float(g("guidance_scale")) if g("guidance_scale") is not None else None
```

### 2.2 只给一边尺寸（只填宽或只填高）会半截传下去

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

回归测试：`tools/check_server_size.py`（语法 + 官方尺寸公式 7 例 + 补全逻辑 8 例）。

## 三、文案不精确但不影响使用的一处

`输出分辨率 output_resolution` 的 label 写「仅编辑模式，默认 1024→输出 832×1248」。

- **"832×1248" 是错的当示例看**：输出尺寸 = 1024² 像素预算按**参考图比例**摊开，
  所以 832×1248 只对应"参考图是 2:3"这一种情况。换张 1:1 的参考图，同样的默认值出 1024×1024。
- **"仅编辑模式" 对 UI 成立、对后端不成立**：管线签名里 `output_resolution` 与模式无关
  （"`output_resolution`² 是像素预算，比例取 `image[-1]`；显式给 width/height 则直接用你给的值"），
  文生图时它同样有效。只是 UI 把这个控件收在编辑模式下（文生图用档位/宽高更直观），所以对用户没有歧义。

**建议改法**（未改，等确认口径）：把 label 改成
`编辑分辨率 output_resolution（仅编辑模式；等于像素预算，比例跟随参考图，默认 1024）`。

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
