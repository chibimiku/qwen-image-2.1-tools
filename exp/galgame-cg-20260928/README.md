# 固定角色 + 指定画风：galgame 约会 CG 实测包

> ⚠️ **正片有已确认的缺陷**（过曝、同一角色出现两次、手部崩坏、景别不一致）。
> 逐条证据、成因分析与修法见 [`DEFECTS.md`](DEFECTS.md)。三张已修补，其余未重出。

配方模板在 [`docs/RECIPE-character-plus-style.md`](../../docs/RECIPE-character-plus-style.md)；
自启说明在 [`docs/AUTOSTART.md`](../../docs/AUTOSTART.md)。

- **角色**：`refs/char.png`（搭配师，1024×1536）
- **画风参考**：`refs/style.png`（832×1216）
- **输出**：1600×896（宽屏上限，见下），40 步，CFG=1.0，无负面词，无后处理

---

## 一、这个包里有什么

| 文件 | 内容 | 入库 |
|---|---|---|
| `out/story-*.png` | 正片 12 幕（seed 42） | ✅ |
| `out/fix-*.png` | 其中 3 幕的**修补版**（见第三节） | ✅ |
| `sheets-final.png` | 成品总表（修补版替换原图后的 12 格） | ✅ |
| `compare-*.png` | 5 组配方对照（街景/咖啡厅/近景/跨 seed） | ✅ |
| `manifest.jsonl` | 42 条请求的完整记录（prompt、实际尺寸、seed、耗时、inputs 尺寸） | ✅ |
| `autostart-verify.txt` | 开机自启的 19 项端到端验证结果 | ✅ |
| `run.py` / `verify.py` / `compare.py` | 驱动、配方自检、拼对照表 | ✅ |
| `out/` 其余 PNG | 过程相（bracket / control / styleonly / padded / boost / seeds） | — |
| `refs/` | 参考图原图（属于用户素材，不重复入库） | — |

**成品是 12 幕**。包里 `story-*` + `fix-*` 共 **15 个 PNG** —— 因为 3 幕的**问题版与修补版都留在盘上**（便于对比），不是 15 幕。

---

## 二、实测结论（与最初设想相反的三件事）

1. **画风参考图不传递"画风"，它传递它自己的主体。**
   只喂 `style.png`、不喂角色图 → 角色被换成紫发双丸子、鞋子带袜子。
   双图里 `<image2>` 的真实作用是给光学与质感线索。

2. **真正控制画风的是样式词，不是参考图。**
   加参考图后画面被拉成明亮白天；把样式词换成具体光学描述（暗底+亮主体+轮廓光+
   密集光点）后才恢复暗调。角色立绘是纯白背景，会把渲染拉向平光。

3. **有整张作废级别的失败模式。** 跨 seed 检查里 seed 20260927 出现**两个人**
   （我们的角色 + 参考图那个白金发少女本人）。所以"每场景跑 3 个 seed"是硬要求。
   **本次正片只跑了 seed 42** —— 这条建议**尚未在正片上执行**，别当成已验证。

---

## 三、正片的三处缺陷与修补

| 场景 | 问题 | 修补做法 |
|---|---|---|
| `06-sunset-bridge` | 画面里有**两个人**（同一角色重复） | prompt 明确 "Exactly one girl in the frame, alone" |
| `01-boutique` | 背景大片纯白留白，不像 CG | 补足环境（衣架、天鹅绒凳、吊灯、木地板） |
| `04-icecream` | 同上 | 补足环境（海边步道、船、灯塔、花盆） |

修补版用**强化样式词**重出，`sheets-final.png` 里已是修补版。

---

## 四、宽屏尺寸的硬边界（实测）

带参考图的请求按"编辑"红线判（`3.65 × MP²`）。**宽屏上限比竖版低**：
竖版 1.92MP 通过，16:9 在 **1600×896（1.43MP）** 以上就是被同比例缩回来。

| 请求 | 实际 |
|---|---|
| 1536×864 | 原样 |
| **1600×896** | **原样 —— 宽屏天花板** |
| 1600×1024 | 1504×960 |
| 1600×1152 | 1408×1024 |
| 1792×1024 / 2048×1152 / 2560×1440 | 1600×896 |

宽高必须是 **64 的倍数**，否则被吸附；一切以响应里的 `size` 为准。

---

## 五、复现

```powershell
cd exp\galgame-cg-20260928

python run.py --phase bracket  --steps 40          # 分辨率选型（宽屏上限）
python run.py --phase control  --width 1600 --height 896 --steps 40   # 只给角色图
python run.py --phase styleonly --width 1600 --height 896             # 只给画风图
python run.py --phase story    --width 1600 --height 896 --seed 42    # 正片 12 幕
python run.py --phase boost    --width 1600 --height 896              # 强化样式词
python run.py --phase seeds    --width 1600 --height 896              # 跨 seed 稳定性
python run.py --phase fix      --width 1600 --height 896              # 三处修补
python verify.py                                   # 配方自检（39 条逐项过）
python compare.py                                  # 拼对照表
```

依赖项目现有的连接方式（`tools/autodl_new.env` + SSH 隧道 + `tools/.qwenkey`）。

**两个协议坑**（踩过，写在 `run.py` 顶部）：
带参考图**必须走 multipart**（`data=` 会 500）；响应是 **JSON + base64**
（`data[0].b64_json`），不是图片字节。

---

## 六、这条记录的边界

- 逐图评分**没做**：本次是人工看一眼定取舍，没有四维打分，也没有跨 seed 的量化统计。
- 正片**只在 seed 42 上跑过**；跨 seed 的不稳定性只在单独 3 张上验证过。
- 修版与原版都在盘上，**选择哪一版由人眼决定**，没有自动判据。
