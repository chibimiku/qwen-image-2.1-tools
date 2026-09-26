# CHANGELOG

## 2026-09-27（凌晨 · 第三十一批）· 服务重启后页面卡死 + 登录框输不进字

### 用户反馈
"如果页面没刷新就重启，这时候页面上会重新弹出 token 的提示，此时 Js 有问题，变得非常卡，
而且用户输入 token 会被立马清空"

### 两个症状，两个不同的原因 —— 都在 401 处理链上

**症状 1：输入被立马清空** —— `showLogin()` 无条件执行 `inp.value = ''`：

```js
function showLogin(msg){
  ov.style.display = 'flex';
  const inp = document.getElementById('loginkey');
  if (inp){ inp.value = ''; setTimeout(...focus..., 60); }   // ← 每次调用都清
}
```

而服务重启后会话 Cookie 失效，**每个在飞的请求都 401**，`on401()` 每个都调 `showLogin()`
（进度轮询 600ms 一次）。于是用户每敲一个字，就被后到的 401 清掉。

**症状 2：非常卡** —— `on401()` 没有任何去重：

```js
async function on401(){
  AUTHED = false;
  log('会话失效或未登录（401）', 'err');        // 每个 401 一行日志
  const st = await sessionState();              // 每个 401 一次额外请求
  if (st.auth_required) showLogin('…');
}
```

叠加三个周期任务（进度 600ms / probe 15s / 会话条 60s）与每次请求失败后的重试，
401 一来就是持续刷屏的额外请求 + 日志，页面自然卡。

### 改动

1. **`showLogin()` 只在首次弹出时清空输入框**（用 `wasOpen` 判断），之后只更新提示文字。
2. **`on401()` 去重**：`_authProbe` 保证同一时刻只有一个 `/v1/session` 探测，
   并发调用挂在同一个 promise 上；日志按 10 秒节流。
3. **不再"401 就立刻重发"**：`get()` / `post()` / 批量的两条路径都改成
   `await on401(); throw`。以前 `on401()` 的返回值恒为 `false`，重试分支根本进不去；
   一旦有人把它改成 `true`，就会变成 401 死循环。现在从写法上杜绝。
4. **`makePoller` 的 `ticking` 挪进 `finally`**：原来若 `get()` 在 401 分支里抛出，
   标志永远停在 `true`，轮询从此停摆（表现是"进度条不动了"）。
5. **`refreshSessionBar()` 复用 `on401` 的探测**，不叠加第二个 `/v1/session`。

### 防回归

新增 `tools/webui_check_invariants.js`：把这几条**踩过的坑**写成不变量一起查 ——
会话失效处理、401 不重试、轮询标志用 finally、尺寸优先级、登录框不自触发。
共 5 组 21 项，全过。

### 验证

`check_ui_js.js` 语法通过；`webui_check_invariants.js` 21 项全过；
`webui_check_size_priority.js` 16 项全过；远端与本地 md5 一致。

---

## 2026-09-27（凌晨 · 第三十批）· 补齐 WebUI 缺失的管线参数（负面词 / CFG / 多图 / sigmas）

### 用户要求
"你刚才提到有反向 prompts 和 cfg 的选项，还有其他选项吗？目前 webui 上没有，你要加上，
还要考虑建议如何选择。"

### 先把管线参数全过一遍

逐个对照 `QwenImage21Pipeline.__call__` 的 23 个参数，结论：

| 参数 | 判断 |
|---|---|
| `negative_prompt` | **要加** —— 此前只在文生图模式显示，而编辑模式恰恰最需要它 |
| `true_cfg_scale` | **要加** —— 官方正名，此前完全没暴露（`guidance_scale` 只是别名） |
| `num_images_per_prompt` | **要加** —— 挑图最实用 |
| `sigmas` | **加，但收在折叠区**（进阶；官方只说"Custom sigmas"，没规定形状） |
| `use_kv_cache` | **不加** —— docstring 明说"切换不会逐比特复现"；它是性能开关，暴露只会让人误以为能调效果 |
| `attention_kwargs` / `*_embeds` / `latents` / `generator` | 不加 —— 要么要传张量描述，要么要求用户自己编码，不属于"点一下能用" |

### 服务端改动

1. multipart 与 JSON **两条路径都接** `true_cfg_scale` / `num_images_per_prompt` / `sigmas`
2. `_parse_sigmas()`：宽松校验（≥2 点、单调递减、0~1），**非法一律静默忽略**退回默认调度，
   不报 500 —— 这是进阶旋钮，不该因为填错就整个请求失败
3. `num_images_per_prompt` 限 1~8；多图时每张种子依次 +1、各自落盘、各自带元数据

### 修掉两个由此暴露的 bug

1. **进度分母取错**：`tot = steps * getattr(pipe, "num_images_per_prompt", 1)` 取的是
   **管线的类属性**而不是请求张数，多图时进度条会早早走满。改成按请求里的张数算。
2. **多图撞序号**：序号靠扫目录得出，而一次出多张时三张都在写盘前就分配好路径，
   于是三张全拿到同一个序号（实测 `59-700001` / `59-700002` / `59-700003`）。
   加了"本批已分配路径"集合来预留。另一个连带 bug：`PNG_METADATA=none` 时整块逻辑被跳过，
   连落盘都不做了 —— 已把路径分配与元数据写入拆开。

### UI 改动

- **负面提示词改成两种模式都显示**（此前 `setMode` 里 `edit` 模式直接隐藏它）
- 新增「高级参数」区：`true_cfg_scale` + `num_images_per_prompt` + 折叠的 `sigmas`
- 两个快捷按钮：**填入人体负面词** / **填入画质负面词**（会顺手把 CFG 设成 2.5，
  因为负面词需要 CFG>1 才生效 —— 否则用户以为填了就有用）
- **联动提示**（`cfgnote`）把两种"白填"直接标出来：
  填了负面词但 CFG=1 / CFG>1 但没填负面词
- **多图显示**：结果区出小图网格，点一张换大图；日志逐张给出 seed 与落盘路径；
  多张都进历史

### 实测（remote/scripts/_params_verify.py）

- 编辑模式（multipart）+ 负面词 + CFG=2.5 → 200，PNG 元数据里两者都记到了 ✅
- `num_images_per_prompt=3` → 真返回 3 张，种子 `[700001,700002,700003]`，
  **三张各自落盘且序号 74/75/76 递增** ✅
- `sigmas` 四种非法值（递增 / 非数字 / 单点 / 超范围）全部安全忽略，合法值可用 ✅

### 文档

`docs/API.md` 参数表补齐；`docs/PROMPT-ANATOMY.md` 新增第六节
「WebUI 上现在能调什么 + 怎么选」，含推荐组合表。

---

## 2026-09-27（凌晨 · 第二十九批）· 「编辑分辨率」少了一个真选项，多了一个假选项

### 用户反馈
"那你咋还有默认 1024 1280三个选项，不是应该就俩么"

### 属实：`默认` 和 `1024` 行为完全等价

```html
<option value="">默认</option>      <!-- value 空 → 服务端不传 → 管线默认 1024 -->
<option value="1024">1024</option>  <!-- value 1024 → 显式传 1024 -->
```

服务端 `if req.get("output_resolution"):` 对空串为假，于是不往管线传；
而管线自己的默认值就是 1024。两条路殊途同归 —— 等于给了个重复选项，
还让用户以为"默认"是个有别于 1024 的第三种模式。

**已改成两个真档位**：

```html
<option value="1024" selected>1024（官方默认，日常够用）</option>
<option value="1280">1280（参考图细节更足，约 2 倍耗时）</option>
```

顺带把 1280 的说明从"参考图细节更足"保留原样（它确实如此），但 tooltip 里
已经写明"不是越大越好"（§第二十八批的实测反例）。

### 边界检查

- 旧 `localStorage` 里存的 `outres: ""`：现在 select 已无该 option，
  `el.value = ""` 会被浏览器忽略，select 保持默认 1024 —— 不会出现空选中。
- 提交处（两处）本来就有 `if ($('outres').value)` 守卫，空值不发，仍然安全。

### 验证

`check_ui_js.js` 语法通过；`webui_check_size_priority.js` 16 项通过；
选项枚举实测只剩 2 个；远端与本地 md5 一致。

---

## 2026-09-27（凌晨 · 第二十八批）· 跟随参考图时档位没置灰（而且会静默覆盖跟随）

### 用户反馈
"当勾选跟随参考图尺寸的时候，还能选图 ratio 但是选了无效，应该是给它灰色"

### 比"没置灰"更严重：优先级反了

用户看到的是"选了无效"，代码里实际情况更糟 —— 提交时档位判在跟随**前面**：

```js
const follow = followRefOn();
if ($('ratio').value) fd.append('aspect_ratio', ...);   // ← 档位赢
else if (!follow) { ... }                               // ← 跟随被跳过
```

也就是说：**跟随开着时选档位，不但不是"无效"，而是悄悄把跟随模式覆盖掉了**。
界面文案还写着"正在跟随参考图尺寸"，实际却按档位出图 —— 用户无从察觉。
（上一批的 `applyFittedRatio` 里也有同样的顺序问题。）

### 改动

1. **置灰**：`syncFollowRef()` 里跟随开启时把档位下拉也 `disabled`（透明度 + not-allowed +
   title 说明"比例由参考图决定，取消勾选才能用档位"）。
   同时**去掉原来的静默清空** `$('ratio').value = ''` —— 就是它让用户一选档位
   就无声切回档位模式，看不出发生了什么。
2. **优先级对齐**：两处提交（单张 + 批量队列）统一改成
   **跟随参考图 > 档位 > 手填宽高**。跟随开着就只发 `output_resolution`。
3. 文案同步：跟随中提示改成"比例和分辨率都由参考图 + output_resolution 决定，档位用不上"。

### 防回归

新增 `tools/webui_check_size_priority.js`：静态核对两处提交分支的顺序
（`follow` 必须在 `aspect_ratio` 之前、宽高排最后），以及 syncFollowRef 里
档位确实被 disable、没有静默清空、用 `on` 变量而非硬编码 true（保证取消勾选能恢复）。
可选传 base URL 时顺带查活的 `/v1/fit`。

这个 bug 出现过两次（上一批一次、这一批一次），所以用脚本钉住而不是靠记性。
（写这个校验器时它自己先报了个假失败 —— 正则被块内第一个 `}` 截断了 —— 也一并修了。）

### 实测

`node tools/webui_check_size_priority.js` → 16 项全部通过；
`node tools/check_ui_js.js` 语法通过；远端与本地 md5 一致。

---

## 2026-09-27（凌晨 · 第二十七批）· 选官方档位不再被拒：同比例缩到能跑

### 用户反馈
"我试了一下用图片，我手动选择 2:3，还是提示：preflight：1696x2528（4.29MP）/26 步
需要约 67.1 GiB 额外显存，当前只有 16.7 GiB 可用……"

顺带一问："自动的话我产出了一张图你看看他实际分辨率怎么走的？"
→ 查了 `/root/qwen-image-2.1/outputs/2026-09-27/04-1691045904.png`：
**1248×832，比例 1.5 = 3:2**，文生图，26 步，元数据完整。也就是说那次是 3:2 档位下的
正常产出（文生图不缩，官方 2K 档位本来就跑得动）—— 和 2:3 失败不是同一件事。

### 上一批（第二十五批）的 /v1/fit 没兜住

服务端侧一切正常（实测 `/v1/fit?all_ratios=true` 正确返回
`2:3/edit → 1056x1568, fits_as_is=false`），但**前端 `applyFittedRatio` 没把建议尺寸套上**，
于是仍按官方 `RATIO_TBL['2:3'] = [1696,2528]` 发出去，撞 preflight。

与其纠结前端为什么没生效，不如**让服务端兜住** —— 这才是根治：

### 改动：服务端自动同比例缩（`enforce_fitting_size`）

用户选档位表达的是"要 2:3 这个**比例**"，不是"要 4.29MP 这个**像素数**"。
所以尺寸确实塞不进显存时，保住比例缩尺寸，而不是拒绝。

- 放在 `_parse_gen_request` 最后一道：**无论客户端算没算对，都不会因为档位尺寸过大而失败**。
- 缩完在 `size_note` 里说明，进元数据、进服务端日志、界面也会显示这行。
- 只影响编辑模式；文生图的已知可用阈值覆盖全部官方 2K 档位，不会被动。
- `QWEN_AUTO_FIT=0` 可恢复成"直接拒绝"。

### 实测：7 个官方档位全部可用（编辑模式 + 参考图）

| 档位 | 官方 | 实际输出 | 比例 |
|---|---|---|---|
| 1:1 | 2048×2048 | 1376×1376 | 1.000 |
| 4:3 | 2400×1792 | 1472×1120 | 1.314 |
| 3:4 | 1792×2400 | 1120×1504 | 0.745 |
| 3:2 | 2528×1696 | 1568×1056 | 1.485 |
| 2:3 | 1696×2528 | 1056×1568 | 0.673 |
| 16:9 | 2752×1536 | 1728×960 | 1.800 |
| 9:16 | 1536×2752 | 960×1728 | 0.556 |

7/7 通过（以前 2:3 / 3:2 / 16:9 这些在编辑模式下全是 507）。

### 文档

`docs/API.md` 补 3.9.4 节。现在**任何合法请求都不会因为档位尺寸而失败**了。

---

## 2026-09-26（深夜 · 第二十六批）· 生成图自动落盘（outputs/日期/序号-seed.png）

### 用户反馈
"这个 output 不自动保存有点离谱，你先修改一下，自动保存下来，以 YYYY-MM-DD 为格式建立
文件夹下面按 序号-seed.png 的格式自动保存。但是你要把 output 下面加到 ignore 里，
不要把产物提交到 git"

用户说得对。查证：`server.py` 里 `OUT_DIR` **只定义、从未被使用**，
服务端不往 outputs 写任何文件 —— 界面出的图不点「下载当前图」就彻底没了。

### 改动

1. **每次生成自动落盘**：`<OUT_DIR>/YYYY-MM-DD/序号-seed.png`。
   - 序号当天连续递增（两位补零）；分配时只认形如 `NN-` 的文件，
     所以根目录里手工命名的历史图（`hug_two_people.png` 之类）不会被算进序号。
   - 并发写入有锁保护，不会撞号。
   - 落盘失败**不影响出图**（只记一行日志）—— 存不下来不该让用户拿不到图。
   - `QWEN_SAVE_OUTPUTS=0` 可关；`QWEN_OUT_DIR` 可换根目录。
2. **落盘的那份与回包逐字节一致**：服务端先算好带元数据的字节，同一份既写盘又 base64 回包
   （不是转两次）。图里的 iTXt 元数据也含 `saved_path`，响应里同样给。
3. **UI 提示**：完成日志里多一行 `↳ 已自动保存：/root/.../01-1834720519.png`。
4. **`.gitignore` 加 `outputs/`**（含 `**/outputs/`）—— 产物绝不提交。
   已用 `git check-ignore -v` 验证生效，`git ls-files outputs` 为空。

### 实现时踩到的三个坑（都已修）

1. **变量名写错**：`save_output()` 里该用 `item` 却写了 `meta`，
   落盘直接抛 `NameError` 被 except 吞掉，表面"成功"实际没存。
   查日志才发现：`[save] 落盘失败（不影响回包）：NameError: name 'meta' is not defined`。
2. **顺序错了**：先序列化元数据再定路径 → 文件里的元数据缺 `saved_path`，
   磁盘那份与回包那份对不上。改成 **先定路径 → 写进元数据 → 再序列化 → 最后写盘**。
3. **落点分裂**：原 `OUT_DIR` 按 `MODEL_DIR` 的父目录算，权重在 `/root/autodl-tmp`
   时落到 `/root/autodl-tmp/outputs`，而文档、`bootstrap.sh`、以及用户原来那 16 张
   都在 `/root/qwen-image-2.1/outputs` —— 产物分了两处。
   改成跟代码走（`<service 目录>/../outputs`），换机、换权重位置都一致。

### 验证（remote/scripts/_save_verify.py）

连出 3 张：

| 检查 | 结果 |
|---|---|
| `saved_path` 在回包里 | `/root/qwen-image-2.1/outputs/2026-09-27/01-1000.png` ✅ |
| 命名格式 `序号-seed.png` | 序号 01/02/03，seed 与返回值一致 ✅ |
| 序号从 1 连续、不跳号 | `[1,2,3]` ✅ |
| 文件与回包逐字节一致 | 3/3 通过 ✅ |
| 根目录历史图不被算进序号 | 18 个散图 + 日期目录共存 ✅ |

### 文档

`docs/API.md` 补 3.9.3 节（路径规则、关掉的开关、失败不影响出图）。

---

## 2026-09-26（深夜 · 第二十五批）· 选比例后自动给出"能跑的尺寸"

### 用户反馈
"我想手动修改比例就会提示失败太大，这块有办法我选定比例之后智能计算下合适的规格吗？"
（贴的是 preflight 拒绝：`1696x2528/26 steps 需要约 67.1 GiB，当前只有 16.6 GiB`
—— 选 2:3 档位直接套了官方 2K 尺寸 4.29MP，编辑模式必炸）

### 改动

1. **新增 `GET /v1/fit`**：按实测标定的显存模型反算"同比例、能跑的尺寸"。
   `all_ratios=true` 一次给全部 7 个档位 × 两种模式（UI 初始化只需一条请求）。
2. **档位下拉直接显示结果**：`2:3 · 官方 1696×2528 → 能跑 1120×1664`。
   编辑模式选中跑不动的档位时，**自动**把宽高换成建议值并解除"跟随参考图"
   （跟随开着时请求根本不带宽高，不解除的话填了也白填 —— 实现时踩到的）。
3. **preflight 错误里带上建议尺寸**：507 的 detail 直接写
   「同比例能跑的最大尺寸：1120x1664（1.86MP，同一比例 0.671）」。
4. **一键修正**：失败提示下方出现「改成 1120×1664 再试」按钮，点了就套用并解除跟随；
   批量队列里失败的条目也有个「修」按钮。

### 关键：判据用实测基线，不用公式外推

- **编辑**：实测红线 1.92MP 通过 / 2.17MP OOM → 以上限 1.92MP 为准，
  显存更紧时按 `mp ∝ √(free/16.5)` 收缩。落点 1.86~1.89MP，在安全区内。
- **文生图**：先把官方 7 个 2K 档位**全部实测一遍**（`remote/scripts/_t2i_2k_check.py`），
  结果 **7/7 全过**（4.19~4.30MP，各约 60s @20 步），于是阈值给到 4.35MP 直接放行。
  一开始我按 2048² 外推成 4.2MP，会把 4:3/16:9 的官方档位误判成"要缩"，实测后才定准。
- **原尺寸能跑就原样返回**（`resized:false`）：官方档位是模型按它训练的，能跑就别动。
  （修之前 1:1 会被算成 2080×2080 这种既非官方又没意义的尺寸。）

### 实测

| 项目 | 结果 |
|---|---|
| 编辑 7 个档位建议值 | 1.86~1.89MP，全部落在实测安全区 ✅ |
| 文生图 7 个官方档位 | `fits_as_is=true`，尺寸原样保留 ✅ |
| 按建议尺寸 1120×1664 跑编辑 | HTTP 200 ✅ |
| 文生图官方 2K 档位实测 | 7/7 通过（存量能力没被新判断误伤） |

### 文档

`docs/API.md` 补 3.9.2 节。现在"编辑上限 1.92MP"有了可执行入口（`/v1/fit`），
不再是让用户自己猜一个数。

---

## 2026-09-26（深夜 · 第二十四批）· 人体复检小模型：500M 换成 2.2B（500M 根本答不出结论）

### 用户要求

"有个新增功能是跑完了视觉小模型看一下是否符合人体比例自动重载，你先把小模型给下载好装上"
—— 装是装上了，然后发现装上也没用；顺藤摸瓜换了一个真能用的。

### 一、500M 装好了，但它答不出可解析的结论

`HuggingFaceTB/SmolVLM-500M-Instruct` 落到实例 HF 缓存（校验：`model.safetensors` 的
sha256 与官方 LFS oid 逐位相同；补上了缺失的 tokenizer / preprocessor 六个文件）。
CPU 加载 39s、判一张 13~30s、常驻 3.1G 内存、**显存 0**。然后真跑：

| 图 | 服务原指令下的原始输出 |
|---|---|
| 正常全身图 | `'PASS.'` |
| 另一张正常图 | `'PASS.'` |
| **一个身体两个头**（照 prompt 生成的真缺陷） | `'PASS.'` |

服务期望 `PASS|置信度|理由`，于是 100% 落进 "unparseable" → fail-open →
**自动换 seed 重跑从来没触发过**。换问法（一句话/两句/极简）、换首 token 打分，全都不行：
这个体量只会回一个词。结论：**500M 承担不了这个判断**（用户据此选了换 2.2B）。

### 二、换 `SmolVLM2-2.2B-Instruct`：判定真的出来了

同一条链路（实例上真跑，`anatomy_check=true`，768×1024/10 步）：

| | 500M | 2.2B |
|---|---|---|
| 原始输出 | `'PASS.'` | `'PASS\|0.9999999999999999\|The image is a full body photo of one woman standing with natural proportions. Both legs are visible.'` |
| 解析结果 | `label=uncertain` / `fail_open=true` / `"checker returned an unparseable verdict"` | `label=pass` / `fail_open=false` / 理由具体到"两条腿都可见" |
| 单张耗时（CPU） | 13~30s | 16~40s（bf16 中位 ~26s） |
| 显存 | 0 | 0（CPU 上跑） |

### 三、但它仍然偏保守（如实记录，别高估这道闸门）

造了一张"**一个身体两个头**"的对照图（prompt 直接要求两个头，肉眼可见）：

| 问法 | 2.2B | 500M |
|---|---|---|
| 数几个头 | **`2`** ✅ | `2.` ✅ |
| 自由描述 | **`A person with two faces stands against a plain background.`** ✅ | `A woman is wearing grey overalls…` ❌ 漏了 |
| 去掉"不确定就 PASS"兜底的强硬 PASS/FAIL | `PASS` ❌ | `PASS.` ❌ |

**它看得见，但一问 PASS/FAIL 就答 PASS。** 所以这道闸门是"能挡就挡"，不是"必定拦下"。
要更准，下一步要么换更大的 VLM，要么改成可核对的问法（"数几个头/几条腿" vs "几个人"，
由代码算差值再判）。这段如实写进了 `docs/API.md` 与 `service/anatomy_check.py` 的模块注释。

### 四、装它的路上踩到的三件事

1. **HF 下不动**：同一分片实测 HF 直连（学术加速）**0.21 MB/s**、hf-mirror 1.9 MB/s、
   **ModelScope 9.5 MB/s**。8.6 GB 权重（fp32 两分片）走 ModelScope 15 分钟下完，
   走 HF 一个多小时还中途卡死（`.incomplete` 停住不动）。新增
   `service/scripts/download_anatomy_model.sh`：ModelScope 下载 + 对着官方清单逐个比大小。
2. **少了依赖**：SmolVLM2 的 processor 需要 `num2words`（500M 那版不需要），报错
   `ImportError: Package num2words is required to run SmolVLM processor`。已写进 `bootstrap.sh`。
3. **精度**：本机 Xeon 8470Q（`avx512_bf16` + `amx_bf16`），CPU 上 bf16 比 fp32
   **快约 1.8 倍**（同图 38.4s → 20.3s）。新增 `QWEN_ANATOMY_DTYPE=auto`：
   GPU→float16、CPU→bfloat16；老 CPU 显式设 `float32`。

### 五、落地状态

- `anatomy_check.py` 默认模型 = `HuggingFaceTB/SmolVLM2-2.2B-Instruct`；`/health` 里
  `anatomy_checker` 增加 `dtype` 与 `max_edge` 字段（未加载时也会报出将要用的精度）；
- 实例 `qwen_env.sh` **追加**了 `QWEN_ANATOMY_MODEL=/root/autodl-tmp/models/SmolVLM2-2.2B-Instruct`
  等四行（只追加，真 key 一个字节没动，改前留了 `qwen_env.sh.bak.*`）；那份文件此前是旧版，
  连复检配置段都没有 —— 所以不给绝对路径的话，服务会去 HF 拉 8.6 GB；
- `download_anatomy_model.sh` 与 `bootstrap.sh` 已随 `deploy_service.py` 上链；
- 端到端：`anatomy_check=true` → HTTP 200，4.1s 出图 + 26.4s 复检，
  `label=pass / fail_open=false / reason=…natural proportions, both legs visible`。
- 验证脚本：`remote/scripts/_test_anatomy_2b.sh`（文件核对 + 行为 + 耗时）、
  `_diag_2b_vs_500m.sh`（对照诊断）、`_fix_instance_env_and_e2e.sh`（改 env + 重启 + 端到端）。

### 六、顺带（与第二十三批的批量队列对齐）

批量队列结束时**不再**把最后一张的 seed 填回输入框 —— 那和第十一批定的约定冲突
（留空/负数 = 随机；只有"点某张图想看复现"时才回填）。现在改成：队列列表里每张的
缩略图可点，点了才把该张的 seed 填进输入框（`batchUseSeed()`），结束只写一行日志。
`tools/webui_logic_check.py` 的检查也从"只允许 2 处写 seed 输入框"改成按入口分类：
清空 / `copyPrompt` / `showHist` / `batchUseSeed` 之外任何写 seed 的代码都算 FAIL。

---

## 2026-09-26（深夜 · 第二十三批）· 批量队列（一行一个 prompt，两级停止）

### 用户要求
"增加一个输入框为批量输入，一行一个，自动排队列，会显示当前队列长度和当前任务进度，
支持点击停止队列（跑完当前的任务），再次点击则连当前任务都停止"

### 设计取舍：队列放客户端，服务端只补"真正能中断"

- 队列**跑在浏览器里**：能复用已验证的 `/v1/images/generations`（JSON 与 multipart 都行，
  所以带参考图的编辑也能批量），也让「只停队列」变得完全不需要服务端参与 —— 不发下一个就完了。
- 服务端此前**没有任何办法中断正在跑的生成**：`DELETE /v1/jobs/{id}` 只对 `queued` 生效，
  一旦 `running` 就干瞪眼。这才是这次真正要补的能力。

### 服务端：真中断

在采样回调最前面加中断检查，命中就抛 `GenerationCancelled` 穿过管线，去噪当场停：

```python
def _on_step(...):
    if cancel_requested(prog["request_id"]):
        raise GenerationCancelled(prog["request_id"])   # 必须在 try 之外
    try: idx = int(step ...)
    except Exception: idx = prog["step"] + 1
```

新增 `POST /v1/progress/{request_id}/cancel`（同步接口没有 job_id，按 request_id 取消），
被取消的请求返回 **499**（不是 500 —— 调用方要能区分"我取消了"和"真出错"）。
`DELETE /v1/jobs/{id}` 现在也能中断 `running`，两者都支持 `?grace_s=`。

### 实现时踩到的两个坑（都已修）

1. **异常被吞**：中断检查原本写在那段 `except Exception: idx = ...` 里面，
   异常直接被吃掉，等于取消无效。必须放在 try 之外。
2. **信号残留**：取消过 A 之后，用同一个 `request_id` 再跑 B，B 会在第一步被误杀。
   现在 `_new_progress()` 开头就 `clear_cancel(rid)`。
   （验证脚本两次跑用的是同一个 id，正好覆盖这个场景。）

### UI

- 左下新增「批量输入」折叠区：一行一个 prompt 的文本框 + 开始/停止队列。
- 队列状态行：**待跑条数 / 已完成 n/N / 失败 / 跳过**；下方队列进度条；
  底部列表逐条显示状态（▶ 进行中 / ✓ 完成 / ! 失败 / ✕ 取消）+ 缩略图 + 耗时，可单张下载。
- **停止是两级的**：第一次点「停止队列」→ 当前这张跑完就停，后面的标记为取消；
  正在跑的时候再点一次（或点「立即中止当前」）→ 调 `/cancel` 连当前一起中断。
- 编辑模式下批量会带上当前参考图（走 multipart），尺寸逻辑与单张一致（跟随开关照样生效）。
- 每张各自掷种子（开跑前清空 seed 输入框）；队列结束时把最后一张的种子填回去。
- 缩略图只保留最近 8 张并主动 `revokeObjectURL`，避免几十张 base64 堆在内存里。

### 实测（remote/scripts/_cancel_verify.py）

| 场景 | 结果 |
|---|---|
| 40 步任务走到第 26 步按取消 | **0.8s 内**结束，返回 499 ✅ |
| 第 3 步按取消 | 0.5s 内结束，返回 499 ✅ |
| 进度状态 | 变成 `canceled`，`error=canceled by user` ✅ |
| 同一 request_id 取消后再跑 | 正常出图，**不被误伤** ✅ |

### 工具

`tools/check_ui_js.js` 的互相调用检测修了两处误报根因：先剥注释，以及用
"函数起始位置数组"切片而不是 `\nfunction `（函数之间的注释块会把下一个函数的声明
包进来，凭空造出环）。现在只剩 `renderThumbs ↔ rmFile` 这一个真实的良性环。

---

## 2026-09-26（深夜 · 第二十二批）· 生成图自带元数据（模型 hash / 输入 hash / 全部参数）

### 用户要求
"历史生成图的 png 里面有 Metadata 记录生成信息吗？没有的话添加一个逻辑，
注意还要可以兼容后续加的字段，要记录所有的生成信息，例如模型 hash，输入的内容，
图片的话要图片 hash"

### 先查：一点都没有

实测 8 张旧图（`/root/qwen-image-2.1/outputs/*.png` 等）：`info keys` 全空、EXIF 0 个 tag。
PIL 默认不写任何生成信息，`QwenImage21PipelineOutput` 也只有 `images`，服务端此前也没补。
**旧图无法追溯补回**（信息已经丢了），元数据从这一版之后的新图开始才有。

### 设计（前向兼容是硬要求）

- 载荷放在 PNG 的 **iTXt** 文本块，键名 `qwen_image_21`，UTF-8 JSON。
  选 iTXt 而不是 tEXt：tEXt 是 latin-1，中文 prompt 会截断。
- 同时写一份 `parameters` 纯文本键，兼容 A1111 / ComfyUI 那类按惯例读它的工具。
- **带版本号**：`{"schema": "qwen-image-2.1/generation", "schema_version": 1, ...}`；
  读取方约定忽略不认识的字段 —— 加字段不破坏老读取方。有专门测试覆盖这条。
- 关得掉：`QWEN_PNG_METADATA=none`。

### 记录了什么

模型身份（**全量 SHA-256**，29 个文件 / 33.1 GB，启动后台算一次并落盘缓存；
`state=partial` 时退回 `light_digest` 并如实标注）、prompt / negative /
尺寸 / steps / **实际种子** / seed_given / CFG / 参考图逐张 sha256 + 尺寸 + 文件名
（`index` 对应 prompt 里的 `<imageN>`）、耗时分段、torch/CUDA/GPU/Python 版本、
审图结果（开了才有）。API 响应里给一份精简版，不占 base64 体积。

### 实现中撞到的两个真问题（都已修）

1. **文件自身的哈希不能存在文件里**（自指）。所以拆成两个指纹：
   - `output.content_sha256` — 写进 PNG，用于认图
   - `output.png_sha256` — 只在响应里，用于认文件
2. **PNG 编码字节不能当内容指纹**。实测：本地 Pillow 与服务端对同一张图写出的字节不同
   （编码依赖 zlib/Pillow 版本）。改成对**解码后像素**做哈希（统一 RGBA + 尺寸拌入），
   跨机器、跨 Pillow 版本稳定。这条是本地 `--verify` 对不上时发现的。

### 验证（remote/scripts/_meta_verify.py）

21 项断言全过 ✅：元数据存在 / schema 版本化 / prompt 原文 / seed 与响应一致 /
模型全量 hash / 环境信息 / 两个哈希各自的语义 / 输入图 hash 与 `<imageN>` 编号对应 /
**未知字段被忽略且不丢数据** / 体积开销 +1.6 KB。

跨机器验证：实例生成 → 下载到本地 → `python tools/read_metadata.py --verify`
→ **内容校验通过**（两端 Pillow 版本不同）。

### 工具

- `tools/read_metadata.py` — 读元数据（`--json` / `--verify` / 支持 glob 批量）
- `tools/ssh_retry.py` — 实例 SSH 偶发 "Error reading SSH protocol banner"，
  带重试的调用封装
- `docs/METADATA.md` — 字段表、两个哈希的区别、复现步骤、校验代码

---

## 2026-09-26（晚 · 第二十一批）· 选项文字折到下一行 + seed 的两个逻辑 bug

### 用户反馈

1. "选项对钩后面的说明文字折到下行了"
2. "每次生成图之后不应该回填随机数，用户留空或者填 <0 的数都是随机，点击某张图想要复现时才填这个历史记录的 seed"

### 问题 1：纯 CSS 层叠事故（一眼能看出根因）

`.chk` 早在第 33 行就写了 `display:flex`（对钩与说明文字同一行），后来有人补开关时
又加了一条 `.chk{display:block}`。两条同权重，**后写的赢** —— `label` 于是回到全局的
`label{display:block}`，说明文字就被挤到对钩下面另起一行。

修法：删掉那条覆盖，并把 `label` 明确声明成 flex 项：

```css
.chk input{width:auto;flex:0 0 auto;margin:3px 0 0}
.chk label{display:block;flex:1 1 auto;min-width:0;margin:0;font-size:13px;
           color:var(--fg);line-height:1.6}
```

长文本现在在**自身宽度内折行**，而不是整体换到对钩下面。

### 问题 2：seed 有两处错，一处是假的可复现参数

**a) 负数被当成真种子用。** multipart 分支 `int(g("seed"))`、JSON 分支 `b.get("seed")`，
`seed=-5` 会原样进 `torch.Generator().manual_seed(-5)`，响应里还把 `-5` 回给用户 ——
照抄这个数并不能复现。两条分支现在共用 `_norm_seed()`：`None` / `""` / 负数 一律 → `None`。

**b) 出图后把随机种子写回输入框。** 上一批为了"想复现时有个值可抄"做了自动回填（第 1028 行），
副作用是**留空从此变成固定**：用户不动它，下一张就是上一张的复刻。现在：

| 行为 | 改成 |
|---|---|
| 出图后回填 seed 输入框 | **不回填**（留空就一直随机），实际种子仍显示在右上角卡片与历史里 |
| 想复现 | **点右侧历史的缩略图** —— 这一下才把该图的 seed 填进输入框（带一行日志） |
| 「复用当前参数」 | 仍带上 seed，日志注明"想重新随机就把 seed 清空" |
| CSS / 文案 | seed tooltip 与 placeholder 改成"留空或负数=随机" |

### 实测

实例上真跑（`remote/scripts/_verify_ui_seed_fix.sh`，走 127.0.0.1:6006）：

| 请求 | 响应 |
|---|---|
| 不传 seed | `seed=854362748 seed_given=false` ✅ |
| `seed=-5` / `-1` | 随机，`seed_given=false` ✅ |
| `seed=0` | `seed=0 seed_given=true` ✅（0 是合法种子） |
| `seed=4242` | `seed=4242 seed_given=true` ✅ |
| 编辑 multipart `seed=-7` / `7` | 随机 / `seed=7` ✅ |

**回归测试（新增，纯本地、不连实例）：** `python tools/webui_logic_check.py`
- `tools/webui_dom_check.js` 用 DOM 桩子在 Node 里**真跑页面脚本**：`seed=""`/`"-5"` →
  `params().seed === undefined`；`showHist(0)` → 输入框变成该图 seed；清空 → 又回到随机。
  （本沙箱禁止启动 msedge/chrome，所以走 Node 桩子；`webui_logic_check.py` 里附账号
  `.chk` 的 CSS 级联检查，确保最终的 `display` 是 `flex`。）
- 11 项全过。

---

## 2026-09-26（晚 · 第二十批）· 留空种子会错报成 0

### 用户反馈
"我留空随机种子最后生成的时候写的是 0，它到底是随机的还是固定的？应该把随机到了什么种子填进去"

### 是真 bug：随机是真的，但报的 0 是假的

原实现：不传 `seed` → `generator = None` → 管线走 `randn_tensor` 的全局 RNG
（进程启动时随机播种，所以**每次确实不一样**）；
但响应里写的是 `"seed": (seed + i) if seed is not None else i` —— **报 0**。

问题在于 `seed=0` 和"不传 seed"**并不等价**：拿返回的 0 去复现，只会得到另一张随机图。
等于给了一个看着能用、实际无效的复现参数。

### 修法：自己掷种子，如实返回

```python
seed_given = seed is not None
if not seed_given:
    seed = random.randrange(0, 2 ** 31 - 1)
generator = torch.Generator("cuda" if ... else "cpu").manual_seed(int(seed))
```

于是"随机生成"和"记下种子可复现"同时成立。响应新增 `seed_given` 标明种子来源；
多图时每张种子依次 +1。

### UI

- 出图后把实际种子**填回 seed 输入框**（这是用户真正要的："应该把随机到了什么种子填进去"）。
- 完成日志带上 `· seed 1319355784（本次自动掷的，已填回输入框）`。
- seed 标签补 tooltip：讲清"留空 ≠ seed 0"。

### 实测（remote/scripts/_seed_check.py，全部通过）

| 场景 | 结果 |
|---|---|
| 留空连跑两次 | 种子 1319355784 / 559269871，**不同** ✅；`seed_given=false` ✅ |
| 用第一次返回的种子复现 | md5 与第一次**逐字节相同** ✅ |
| 种子 +1 | 出图不同 ✅ |
| 同一指定种子连跑两次 | md5 一致 ✅ |

---

## 2026-09-26（晚 · 第十九批）· 长图输出变方的 bug + 进度条"卡在 100%"

### 用户反馈（附截图）
1. "到 100% 之后就卡死了，等了很久才出来"
2. "输入是长图，输出变成 1024×1024 了，预期输出应该跟参考图"

### 问题 2：确认是真 bug，根因在 UI 自己挖的坑

`<input id="width" value="1024">` —— 宽高**出厂就预填 1024×1024**。
编辑器提交时只要 `$('width').value` 非空就发出去，于是每个编辑请求都带着
`width=1024&height=1024`，后端的 `explicit_size` 分支直接用它，**参考图比例被无声覆盖**。
而 UI 文案还写着"留空宽高：比例跟随参考图" —— 自相矛盾，用户没填也等于填了。

修法：新增**「跟随参考图尺寸」开关，编辑模式下默认勾选**。
- 勾上：请求不带 width/height（哪怕输入框里有预填值），后端按 `output_resolution`
  当像素预算、比例取最后一张参考图。宽高输入置灰。
- 取消：解锁手填，这是把编辑分辨率抬到 2K 的唯一杠杆。
- 新增**尺寸预演行**：上传参考图后直接显示"参考图 512×1216（比例 0.421）
  → 输出 672×1568（1.05MP）"，用的是和官方 `calculate_dimensions` 同一套算法；
  超 1.92MP 会标红提示。

实测：参考图 512×1216（比例 0.421）→ 输出 **672×1568（比例 0.429）**，跟参考图一致 ✅

### 问题 1：服务器侧复刻不出来，如实记录

造了完全相同的请求反复测，并**直接打印 `/v1/progress/{rid}` 的原始响应**：

```
step 11/12  pct=91.7  elapsed=7.83s
（下一次查询）status=done phase=done pct=100 elapsed=8.91s
timing: decode_s=0.0  encode_s=0.17   ← 去噪之后的全部开销
```

去噪之后只有 **0.17 秒**（VAE 解码 0.0s + PNG 编码 0.17s）。另外也排除了两个嫌疑：
- `torch.cuda.empty_cache()`：实测 <1ms（曾怀疑它在持锁状态下阻塞）
- 首请求加载权重：`loaded:true` 时不存在

**所以服务器侧没有可复现的卡顿**。时间对不上，说明"卡很久"更可能发生在浏览器端：
1.38 MB 的 base64 JSON 要塞进一个模板字符串注入 innerHTML，解码长图本身要时间。

**做了两件不依赖时序的事**（哪怕是浏览器侧的等待，现在也能看清）：
1. **进度条收尾阶段收回 99%**，不再假装 100% 之后还在等：[服务端](../service/server.py)
   在最后一步回调跑完但图还没好的窗口里上报 `status=decoding`（用 `steps_done >= total`
   判断，不依赖轮询能否抓到那一瞬），前端把条子压回 99% 并显示"去噪完成，正在解码 / 收尾…"。
2. 出图日志补上**分段时间**：`decode_s` / `encode_s` 随 `timing` 返回，卡在哪一段一眼可见。

同时把 PNG 编码降到 `compress_level=1`（默认 6 级在 1024² 上要多花几百毫秒，
对生成图这点压缩收益没意义）。

### 工具

`tools/check_ui_js.js` 新增**互相调用检测**：A 调 B、B 又调 A 且无终止条件就是死递归，
这种 bug 只在浏览器里炸、静态看不见。本轮改 UI 时真的踩到一次
（`syncRatio ↔ syncFollowRef` 在编辑模式下直接栈溢出），靠这个检查发现并修掉。

---

## 2026-09-26（下午 · 第十八批）· README 写成 agent 可执行的部署说明

### 用户要求
"更新 README，告诉 agent 拉下代码之后应该怎么部署。"

### README 新增「部署（给 agent 的执行说明）」

按"一个刚 clone 下来、什么都不知道的 agent 照着敲就能通"来写的：

- **先讲清前置条件**：≥40 GB 显存的实例、SSH 域名/端口/密码从哪来、缺了要**先问用户别猜**、
  权重不在仓库里（33 GB 由步骤 2 自己下，且不能放系统盘）。
- **步骤 0 定位** → **步骤 1 传服务端（本机 3 秒）** → **步骤 2 装依赖+下权重+起服务
  （实例上 20~40 分钟）** → **步骤 3 验证**。
- **每条命令都标了在哪台机器上跑**，并给期望输出（例如 `完成：传输 N / 跳过(相同) M / 保护 1`）。
- **验收标准做成表格**：`/health` 要 `loaded:true`、`check_deploy.py` 要 15/15、
  出图要返回 `b64_json`。
- **排障表**：401、400、OOM、`Authentication failed`、`loaded:false`、
  `一致*` 分别对应的原因与处理。
- 明确三条**禁令**：不要 `--force-env`（会覆盖实例真实 key）、
  不要绕过 `serve.sh` 直接 `python service/server.py`（`QWEN_TILE_VAE` 会退化）、
  不要把权重放系统盘。

### 配套的三处改动（否则 README 里的命令跑不通）

1. **`tools/deploy_service.py --save-env`**：把这次的 host/port/password 写进
   `tools/autodl.env`（git-ignored），之后一条命令即可部署。
   文件已存在时**拒绝覆盖**（除非 `--force`），免得把别人的真实凭据冲掉。
2. **凭据读取统一**：`tools/autodl_ssh.py` 原来只读 `tools/autodl2.env`，
   而 `autodl_run.py` 读 `autodl.env` —— 存了一份另一个工具不认。
   现在两个文件名都读（后者覆盖前者，保留旧名兼容），`autodl_run.py` 与
   `check_deploy.py` 也一并走同一份。
3. README 后面补「实例上怎么操作（已部署好之后）」与「本机快速开始」两节，
   把 `serve.sh` 启停、`show_url.sh`、日志位置、隧道用法集中列出。

### 实测

README 步骤 3.3 **原样执行通过**：
`a red cube on a white table`，1024²/20 步，返回含 `"b64_json"` 的 JSON。
`python tools/autodl_ssh.py health` → `"loaded":true`。

---

## 2026-09-26（下午 · 第十七批）· 部署资产归一 + 两个部署工具（用户追问触发）

### 用户问题
"这个 tools 包含服务端部署的内容（不算模型，只是服务端的 server 等）了吗？"

### 答案：当时不含。部署内容散在 `service/` 和 `remote/scripts/` 两处，而且**两处不一致**

对账查出来的真实情况（`tools/check_deploy.py` 第一次运行）：

| 问题 | 证据 |
|---|---|
| **同一份脚本存在两版且内容不同** | `remote/scripts/serve.sh` 缺 `QWEN_TILE_VAE` 兜底、缺鉴权状态打印；`remote/scripts/qwen_env.sh` 里 `QWEN_TILE_VAE` 默认还是 **0** |
| 仓库里没有部署说明 | 没有任何文件回答"哪个本地文件对应实例上哪个路径" |
| 仓库里没有部署工具 | 一直是手敲 `autodl_run.py --put`，逐个文件传，容易漏 |

`QWEN_TILE_VAE=0` 那份尤其危险 —— 2048² 会直接崩在 VAE 上采样层，而它长得和权威版几乎一样。

### 改动

1. **`service/` 变成唯一部署载荷，结构与实例一一对应**：

   ```
   service/server.py           → /root/qwen-image-2.1/service/server.py
   service/ui/index.html       → /root/qwen-image-2.1/service/ui/index.html
   service/scripts/serve.sh    → /root/qwen-image-2.1/scripts/serve.sh
   service/scripts/qwen_env.sh → /root/qwen-image-2.1/qwen_env.sh      ← 唯一提级
   ```

   一次性探测/实验脚本留在 `remote/scripts/`（`_*.sh`），不再放部署件。
   删掉了 `remote/scripts/` 里那 6 个陈旧重复副本。

2. **`tools/deploy_service.py`** —— 整树镜像部署：幂等（比 md5，只传有变化的）、
   自动建目录、**默认保护远端的 `qwen_env.sh`**（那份存着真实 key，覆盖会导致 401），
   要覆盖得显式 `--force-env`。支持 `--dry-run`。

3. **`tools/check_deploy.py`** —— 逐文件对账，输出「一致 / 不一致 / 仓库缺 / 远端无」。
   对 `qwen_env.sh` 做**语义比较**：去掉 `QWEN_API_KEY`/`QWEN_API_KEYS` 两行再比，
   值不同但结构一致就标 `一致*`，不误报成漂移。

4. **两者共用 `tools/deploy_manifest.py`** 的一份路径映射，杜绝"工具 A 认这个路径、
   工具 B 认那个路径"的二次漂移。

5. **新增 [DEPLOY.md](DEPLOY.md)**：目录映射表、依赖清单（强调 `python-multipart`
   必须装，否则 multipart 全 400）、三步部署、四个部署期坑。

### 实测

- `python tools/deploy_service.py`：传输 1 / 跳过 13 / 保护 1（补上了缺失的 `face_fix.py`）
- 再跑一次：传输 0 / 跳过 14 / 保护 1 —— **幂等成立**
- `python tools/check_deploy.py`：**15/15 一致**（其中 `qwen_env.sh` 为 `一致*`）

---

## 2026-09-26（下午 · 第十六批）· 参考图引用语法 + UI 核查 + 首次入库

### 用户提的三件事
1. 检查 UI 的说明文案与参数选项是否符合预期
2. 研究官方文档：用参考图时 prompt 里该怎么引用；UI 上给参考图加 `image1` 之类提示，点击插到光标处
3. 配置 git 并提交到 `chibimiku/qwen-image-2.1-tools`

### 1. 参考图引用语法：`<image1>` / `<image2>` …（编号 = 上传顺序）

查遍官方三处，口径一致：

| 来源 | 内容 |
|---|---|
| `prompt_template_ti2i`（管线源码 L216-220） | 模板里写死 `<image1>`，紧跟视觉 token 占位符 |
| `_get_qwen_prompt_embeds()`（L249-259） | 按 `len(image)` 展开 `<image1>`…`<imageN>` |
| `prompt_rewrite/data/edit_example.jsonl` | `multi_portrait` 示例：「将`<image1>`中的人物和`<image2>`中的人物置入…」 |
| `pe_core.py` 答案契约 + `build_messages` 注释 | `ratio_follow: "<image1>"`；顺序即编号，重排会**静默**改变指代 |

受控实验（`remote/scripts/_imageN_refs.sh`，红圆/蓝三角，固定种子）：
- 不点名 → 两个形状被**融成一个**
- 用 `<image1>`/`<image2>` 点名 → **正确分开**
- 编号对调 / 用自然语言序数 → 这套强语义素材下也正确（所以 `<imageN>` 是"最不易歧义"的选择，不是"唯一能用"的写法）

详见 [EXPERIMENT-ref-syntax.md](EXPERIMENT-ref-syntax.md)。

### 2. UI 改动

- **参考图缩略图下方新增 `<image1>`/`<image2>` 芯片**：点一下把标签插到 prompt 的**当前光标处**（支持选区替换、插完光标落在标签之后）。
- 无图时该位置显示用法提示；有图时显示写法说明（顺序即编号）。
- 缩略图角标标出编号（`image1`、`image2`…），`title` 提示可以用它引用。
- 参考图 tooltip 补一段引用语法，附官方多人物示例原文。

### 3. 核查出的三个真问题（已修）

| 问题 | 现象 | 修法 |
|---|---|---|
| multipart 丢字段 | `negative_prompt` / `guidance_scale` 只有 JSON 分支解析过，用 multipart 传会静默失效 | multipart 分支补上同名字段 |
| **`guidance_scale` 根本不存在** | 管线签名里只有 `true_cfg_scale`。API 文档写着能传 `guidance_scale`，真传了就是 `TypeError: unexpected keyword argument 'guidance_scale'` 500（JSON 路径同样中招，只是从没被测过） | ① `guidance_scale` 映射到 `true_cfg_scale`，两个名字都收；② 调用前用 `inspect.signature(pipe.__call__)` 取真实参数表，不认识的 kwargs 一律丢弃并打日志 |
| 半截尺寸 | 只填 width 或只填 height 时带着 `None` 进预检与管线，在很远的地方炸 `NoneType` | 按参考图比例补成完整一对并 32 对齐 |

改动后实测（`remote/scripts/_fix_check.sh`）：
- T1 multipart + `negative_prompt` + `guidance_scale` → **512×512 出图，2.8s**（原 500）
- T2 只给 width + 参考图 → **HTTP 200**（原 500）
- T3 `/ui` 带上 `renderChips`/`insertTag` → 4 处命中

核查明细（含"确认不用改"的 7 项与 3 条已知限制）见 [UI-AUDIT.md](UI-AUDIT.md)。

### 4. 首次入库

- 仓库：`github.com/chibimiku/qwen-image-2.1-tools`，分支 `main`，沿用作者原有的 MIT LICENSE。
- `.gitignore` 合并：作者模板 + 本项目规则（凭据文件、约 300 MB 实验产物）。
- `.gitattributes` 统一 LF（shell/python 在远端 Linux 跑），只让 `*.bat` 保持 CRLF。
- **凭据清理**：真实主机名/端口/IP 从 `docs/*.md`、`*.example`、`qwen-tunnel.bat`、
  `_probe_bind.sh` 里换成占位符；真实值集中到 git-ignored 的 `tools/instance.env`。
  新增 `tools/scan_secrets.py` 做提交前扫描。
- 新增复核工具 `tools/check_ui_js.js`（UI 内联 JS 语法 + 关键符号自检）、
  `tools/check_server_size.py`（尺寸公式与补全算术）。

---

## 2026-09-26（下午 · 第十五批）· 合并成单入口（用户提问触发）

### 用户问题
"根据管线设置就一个管线，那还有必要分出文生图和编辑吗？"

### 结论：底层是一件事，但判据是"有没有参考图"，不是"选了哪个 Tab"
先验证了三处真分叉：

| 验证项 | 无参考图 | 有参考图 |
|---|---|---|
| 不传尺寸的默认输出 | **2048×2048** | 跟随参考图（768×1024 → 896×1184） |
| 2048² | ✅ 能跑 | ❌ OOM |
| 显存二次项系数 | 0.5 G/MP² | 3.65 G/MP² |

**这解释了我上几轮为什么做错**：我按"模式"去禁用档位/宽高，而正确的判据是"有没有参考图"。

### 改动
1. **后端合并为单入口**：`/v1/images/generations` 现在 `image` 可选，请求体两种都收
   （JSON 用 `image_b64`，multipart 用重复 `image` 字段）。解析逻辑抽成 `_parse_gen_request()`，
   `/v1/images/edits` 变成**转发到同一实现的别名**（保留兼容与"编辑"这个直观叫法）。
2. **尺寸逻辑按判据分流**（不再按 endpoint 分）：
   无图 → 不传尺寸用官方默认 2K；有图 → 不传尺寸按官方公式从参考图推导。
3. **新增 `_derive_size()`，逐字对齐官方 `calculate_dimensions`**。

### 修掉的两个 bug
| bug | 现象 | 原因 |
|---|---|---|
| 有图不传尺寸时崩 500 | `TypeError: unsupported operand type(s) for *: 'NoneType' and 'NoneType'` | 我把宽高设成 `None` 想留给管线推导，但**显存预检要先知道尺寸** → 改成自己推导 |
| 尺寸推导公式错 | 7 个实测里 6 个对不上（宽总是少 16） | 我把取整写成 `floor(.../16)*16`，官方是 **`round(.../32)*32`**；且高要用**未取整**的宽反算。改完后 **7/7 全对** |

### 实测
```
JSON，无图，不传尺寸                 -> 2048x2048
JSON，带 1 张 image_b64              -> 896x1184
multipart，无图                      -> 2048x2048
multipart，1 张图                    -> 896x1184
multipart，2 张图 + width/height      -> 1184x1600
multipart，无图 + aspect_ratio=16:9   -> 2752x1536
/v1/images/edits（旧端点）            -> 等价（转发）
```
离线校验：`tools/check_size_formula.py`（7/7 与实测一致，不需 GPU）。

### 文档
- `docs/API.md`：3.3 改为"统一入口（`image` 可选）"，3.4 改为"别名"。
- `docs/MEASUREMENTS.md` 新增 3.7 节：分叉点表 + 单入口矩阵 + 尺寸公式对齐说明。

### 未做（等确认）
UI 上那两个 Tab **暂时保留**（当作"常用组合"的快捷方式），但底下的分叉判据已经改对了。
要不要进一步去掉 Tab、改成"一个输入框 + 可选参考图"的单表单，等你定。

## 2026-09-26（下午 · 第十四批）· 官方文档落本地

### 新增 `docs/upstream/`（279 KB，离线可读）
| 文件 | 大小 | 说明 |
|---|---|---|
| `qwen-image-2.1-github-README.md` | 20.9 KB | 官方仓库 README（内容最全：Quick Start / 多参考图 / 架构 / 各框架支持） |
| `qwen-image-2.1-hf-modelcard.md` | 5.2 KB | HF 模型卡（含 front-matter：`license: other` / `qwen-research`） |
| `qwen-image-2.1-modelscope-README.md` | 5.3 KB | ModelScope 上的同一份（国内可达） |
| `qwen-image-2.1-LICENSE.txt` | 7.6 KB | Qwen Research License 原文 |
| `qwen-image-2.1-blog.html` | 92.1 KB | qwen.ai 博客 HTML |
| `diffusers-pipeline_qwenimage21.py` | 41.1 KB | **管线实现（尺寸/参数默认值的唯一真相）** |
| `diffusers-transformer_qwenimage21.py` | 46.0 KB | DiT 实现 |
| `diffusers-autoencoder_kl_qwenimage21.py` | 56.8 KB | 64 通道 RGBA VAE 实现 |
| `INDEX.md` | 3.7 KB | 索引：每份文档抓什么事实、已知抓不到的东西、常用 grep 速查 |

- 同步脚本：`python tools/sync_upstream_docs.py`（`--check` 只体检）；
  导出源码脚本：`remote/scripts/export_source.sh`（在实例上跑）。
- 已核对事实并写入索引（来源逐条标注）：多参考图定义、许可证字段、默认 2K / 40 步、
  7 个原生档位、透明提示词前缀、尺寸推导公式、`image` 的"一组图"语义、
  `true_cfg_scale=1.0` 默认不做 CFG、`output_resolution` 同时用于缩放参考图、`use_kv_cache` 默认开。
- **已知抓不到**：qwen.ai 博客正文（SPA，HTML 里没有内容，`blog.txt` 为空）；
  官方示例图（体积大、非必要）；ComfyUI 工作流 JSON（走 diffusers 路线，暂不需要）。

### 顺带确认的两条结论
- HF 模型卡 front-matter 明确 `license: other` + `license_name: qwen-research`
  —— 与 `LICENSE.txt` 一致，**不是 Apache 2.0**，商用需另行授权。
- `calculate_dimensions(target_area, ratio)` 的实现（源码里直接可读）：
  `width = sqrt(target_area * ratio); height = width / ratio`
  —— 与我实测的"预算 + 参考图比例，显式尺寸优先"完全对得上。

## 2026-09-26（下午 · 第十三批）· 读官方文档后修正选项 + 界面问号提示

### 读的文档
官方 GitHub README（`raw.githubusercontent.com/QwenLM/Qwen-Image-2.1/main/README.md`，
内容与 HF 模型卡、qwen.ai blog 一致）。逐条对照后修正了 UI 的选项与说明。

### 直接回答用户的问题：两个人拥抱用哪个接口
**用「图像编辑」+ 两张参考图。** 依据是官方 README 里 *Image Editing (Multiple Reference Images)*
一节：`image=[ref_0, ref_1, ref_2]` + `prompt="These three characters are sitting around a campfire"`
——这就是官方的 multi-subject composition 用法。三个理由：
1. 官方示例就是这个形式，最多 10 张；
2. 只传文字也能画出拥抱，但两人长什么样不受控；给一张只能锁住一个人；
3. **底层是同一个 `QwenImage21Pipeline`**：传 `image` 就是条件生成，不传就是纯文本生成 ——
   "编辑"不等于"只能改一张图"。

### 实测到的行为（并据此改了 UI）
- **多参考图时，输出比例由最后一张决定**：
  A+B → 1024×1024；B+A → 896×1184（管线用 `image[-1]` 算尺寸）。
  仍与文档里 "`image` 顺序有意义" 一致，UI 现在会明确提示"最后一张决定比例"。
- 两张参考图 + 显式 1184×1600 → 成功（14 步 / 22.1s / 每步 1.35s），
  两个人的发色和服装分别对应两张参考图。样例：`test-data/remote_outputs/hug_two_people.png`。
- 同样两张图走 `/v1/images/generations` → 参考图被忽略，只是纯文本生成（符合预期）。

### UI 修正
- **两个 Tab 右侧加问号**：悬停显示"文生图 vs 图像编辑"的完整区别 + 该用哪个 + 官方依据。
- 参考图上方加问号：说明顺序语义（最后一张定比例）、多主体合成、身份保持、1.92MP 上限。
- 步数加问号：官方默认 40，实测 0.51s/步（1024²）、2048² 约 2.6s/步，给出 20~25 / 40 的取舍。
- 档位加问号：列出官方 7 个原生 2K 尺寸，并提醒编辑模式下选 2:3 会 OOM 被预检拦住。
- 透明背景加问号：说明是 64 通道 RGBA VAE 原生生成，附官方推荐提示词格式。
- 参考图缩略图下方新增一行动态说明：单张时"输出比例跟随这张"，多张时
  "多主体合成；默认比例跟随最后一张（文件名）"。

### 文档
- `docs/API.md`：3.4 节标题改为"图像编辑 / 多参考图合成"，加接口选择说明与拥抱示例。
- `docs/MEASUREMENTS.md` 新增 3.6 节：多参考图实测表 + "两个人拥抱用哪个接口"的完整论证。

## 2026-09-26（下午 · 第十二批）· 尺寸规则与显存校准（用户质疑触发的复查）

### 用户质疑
"编辑界面里「快速档位 aspect_ratio」变灰了，这个逻辑是否正确？输入图片本身是有分辨率的。"
—— **质疑成立**，而且我查下去发现比这更严重的问题。

### 查证（读源码 + 实测，不靠印象）
1. `QwenImage21Pipeline.__call__` 源码第 118-124 行：
   `output_resolution²` 是**像素预算**，比例取自参考图，**显式 width/height 优先**。
2. 实测：768×1024 参考图不传尺寸 → 896×1184；传 `width=1088&height=1440` → 1088×1440（**生效**）；
   `output_resolution=1280` → 1120×1472。

### 修的问题
| # | 问题 | 修法 |
|---|---|---|
| 1 | 编辑模式下把**宽高置灰** —— 那是唯一能提分辨率的杠杆，等于把旋钮锁死 | 改为可用，并给出留空/填写两种行为的说明 |
| 2 | 编辑模式下把**档位也置灰**，但档位在编辑路径压根不发送，灰得毫无意义 | 恢复可用；后端 `edits` 新增 `aspect_ratio` 参数并映射官方档位 |
| 3 | 后端 `_generate` 无条件 `kwargs.pop("width"/"height")`，编辑时显式尺寸永远无效 | 新增 `explicit_size` 标记：显式给了就传给管线 |
| 4 | 我那个**线性显存公式严重低估**（2.17MP 估 34.4G，实际 >47G），预检形同虚设 → 用户拿到裸 OOM | 改为 `max(线性, 二次)`，**分模式校准**：编辑 3.65 G/MP²、文生图 0.5 G/MP² |
| 5 | **`QWEN_TILE_VAE` 默认值是 0** —— 文档写"2048² 必须开"，实际一直没开，2048² 必崩 | `qwen_env.sh` / `serve.sh` 都改成默认 1 |
| 6 | 用裸 `python service/server.py` 起服务会漏掉 `serve.sh` 里的 tile_vae 设置 | 记为纪律：只用 `serve.sh` / `bootstrap.sh` 起；文档写明 |

### 实测边界（48G 卡，权重常驻 30.2G，分块 VAE 开启）
| 尺寸 | MP | 结果 |
|---|---|---|
| 1088×1440 | 1.57 | ✅ |
| 1152×1536 | 1.77 | ✅ |
| **1184×1600** | **1.89** | ✅ 上限附近 |
| 1280×1696 | 2.17 | ❌ OOM |
| 1696×2528 | 4.29 | ❌ OOM（原生 2K 编辑做不了，除非 offload） |
| 2048×2048 文生图 | 4.19 | ✅ 峰值 32.5G（**前提：tile_vae=1**） |

### 修完的验证
```
tile_vae=1
文生图 2048²        -> OK 2048x2048  每步 2.626s
编辑 1184×1600      -> OK 1184x1600
编辑 1280×1696      -> 拦住（预检给出建议，不再裸 OOM）
最终 空闲 16.7G / 已用 30.25G / 峰值 33.87G  ← 稳定态
```
离线校验脚本：`tools/check_vram_formula.py`。

### 界面
- 宽高不再在编辑模式置灰；档位两模式都可用。
- 编辑模式下实时提示尺寸风险：>1.92MP 显示"会 OOM（实测 >2.17MP 必失败）；建议 ≤ 1.92MP"，
  1.92~2.17MP 之间显示"接近显存上限，可能失败"，并用 `/health` 的实时空闲显存补充建议。

### 文档
- `docs/MEASUREMENTS.md` 新增 3.2~3.5：尺寸规则表、显存边界表、两个坑、预检公式与校准。
- `docs/API.md`：`width`/`height` 的说明由"会被忽略"更正为"唯一的分辨率杠杆"；
  补 `aspect_ratio`；写明编辑上限 1.92MP。

## 2026-09-26（下午 · 第十一批）· 多 key 支持

### 背景
上一批把 key 从 `1730` 换成 28 位随机串，用户实际使用时输入 `1730` 报"不正确"。
需要新旧并存：换 key 要有过渡期，也便于给自己人发短口令。

### 改动
- 新增 `QWEN_API_KEYS`（逗号/分号/空格分隔）：**里面的 key 与主 key 同等有效**。
- `_valid_keys()` 汇总去重；`_key_ok()` 用 `secrets.compare_digest` 常量时间比较。
- 三处判定统一走 `_key_ok()`：`/v1/*` 守卫、`POST /v1/session`（登录）、`?key=` 查询参数。
- `_spec_url()`（Swagger 的 openapi_url）改用主 key 并做 URL 编码。
- `/health` 的 `auth_required` 现在考虑两个变量。
- 当前配置：主 key = 28 位随机串，`QWEN_API_KEYS=1730`。

### 实测
```
主 key   /v1/models -> 200        1730  /v1/models -> 200
?key=1730            -> 200       错误 key -> 401        无 key -> 401
/docs?key=1730       -> 200
POST /v1/session 主key -> 200     POST /v1/session 1730 -> 200     错 key -> 401
用 1730 登录拿 Cookie 后出图 -> 768×768 OK（每步 0.291s）
```

### 文档
- `docs/API.md`：鉴权一节改成"支持多个 key"，环境变量表加 `QWEN_API_KEYS`。
- `docs/SHARE.md`：换 key 的步骤改成"先留过渡、再删旧 key"。

## 2026-09-26（下午 · 第十批）· Cookie 会话 + 表单记忆

### 1. key 改走 HttpOnly Cookie 会话（替代 localStorage）
用户问"key 能不能放 cookie"—— 能，而且比 localStorage 好，所以直接换了实现：

- 新增 `POST /v1/session`：用 API Key 换会话 Cookie
  （`HttpOnly; SameSite=strict; Secure; Max-Age=86400`），服务端内存里存 token→过期时间。
- 新增 `GET /v1/session`（查当前浏览器是否已登录）、`DELETE /v1/session`（让服务端销毁会话）。
- 鉴权守卫扩成三种带法：Cookie 会话 / `Authorization: Bearer` / `?key=`。
- 前端**彻底不保存 key**：不再有 localStorage 键、不再用 `window.prompt`；
  改为登录遮罩（`#login`）+ 侧栏会话状态（已登录 / 剩余小时 / 退出）。
  带 Cookie 出图、不用任何 header。
- 页面 HTML 里不再出现 key 明文；`localStorage` 现在**只用于表单记忆**。

实测（协议层，未开浏览器）：
```
GET  /v1/session 未登录      -> 200 {"authenticated":false,"auth_required":true}
POST /v1/session 错 key      -> 401
POST /v1/session 正确 key    -> 200  HttpOnly / SameSite=strict / Secure / Max-Age 全有
带 Cookie /v1/models -> 200   不带 -> 401
带 Cookie 出图       -> 512x512 OK
DELETE /v1/session   -> 200   退出后带旧 Cookie -> 401（服务端确实销毁）
页面含 key 明文: 没有
```

### 2. 记住上次的输入内容
- 新增 `qwen_form_v1`：保存 prompt / negative / 宽高 / 档位 / 步数 / seed /
  output_resolution / 透明 / 异步 / 当前模式；`loadForm()` 在启动时恢复并写日志提示。
- 触发时机：字段 `change`/`blur`、档位切换、出图成功后、`beforeunload`。
- **只记输入内容，不记 key**（key 走会话 Cookie）。

### 3. 宽高输入框随档位联动置灰
- 选了「快速档位 aspect_ratio」→ 宽高输入框 `disabled` + 降透明度 + 手型改 not-allowed，
  并显示一行提示"将按 2048×2048 出图（后端按档位解析，忽略上面的宽高）"；
  切回「不使用」自动恢复可编辑。
- 编辑模式下宽高与档位**都置灰**（尺寸由参考图 / `output_resolution` 决定），
  并给出 tooltip 说明"填了也会被忽略"——这是实测过的行为，索性在界面上说清楚。

### 4. 其他
- `/health` 增加 `auth_required` / `ui_key_mode` / `session_ttl_h`。
- `serve.sh status` 打印当前 key 模式与会话有效期。
- 本地脚本新增 `tools/keys.py`（key 从 `tools/.qwenkey` 或环境变量读）；
  测试脚本不再硬编码 key，输出里也做了掩码。

## 2026-09-26（下午 · 第九批）· 修复 key 泄露

### 问题（用户指出）
控制台页面把 `QWEN_API_KEY` 从服务端渲染进 HTML 并自动填好 → **谁打开页面谁就拿到 key**，
加上 key 只有 4 位数字（`1730`），公网地址等于不设防。分享镜像后更严重：
镜像里那份 key 会被所有人共用。

### 修复
1. **新增 `QWEN_UI_KEY` 三态**，页面不再无条件注入 key：
   | 值 | 行为 |
   |---|---|
   | `inject` | 渲染进页面并自动填（只有自己用） |
   | `auto`（新默认） | **不注入**；浏览器首次问一次，存 localStorage |
   | `off` | 页面按无鉴权工作 |
2. **前端加鉴权流程**：`key()` 读取顺序 = 输入框 → localStorage → 询问；
   所有请求（含 `probe` 轮询）遇到 401 统一走 `on401()`：清掉本地 key、重新询问、**原请求自动重试一次**；
   `probe()` 用 `key(true)`（静默）不会反复弹窗；状态栏显示「需要 API Key」。
   没有 key 时点「生成」会在日志里明确提示，不会卡住按钮。
3. **key 换成 28 位随机串**（原 `1730` 作废），旧 key 实测返回 401。
4. **笔记本不再从环境变量读 key**：原实现 `os.environ.get("QWEN_API_KEY")` 等于把 key
   写进笔记本——分享镜像后任何能开 JupyterLab 的人都能读到。改成 `getpass` 运行时输入一次。
5. **笔记本里的服务链接改用公网地址**，不再用 `/jupyter/proxy/6006/`：
   实测该路径下服务收到的 path 带 `/jupyter/proxy/6006` 前缀，路由匹配不上 → 404
   （`/jupyter/proxy/6006/` 本身是 302，`/health` 是 404）。
6. 本地测试脚本的 key 收敛到 `tools/.qwenkey` + `tools/keys.py`，脚本里不再出现明文 key。

### 验证（无头浏览器实测 auto 模式）
```
[check] 页面含 key 明文: False          ← 不再泄露
[check] 注入的 KEY_MODE: auto
boot  | keyMode=auto  keyInput=(空)  conn=服务就绪
A 无 key  → 提示框 1 次后被拦，日志「还没有 API Key：请在左侧输入…」，按钮未卡死
B 有 key（localStorage）→ 提示框 0 次，出图成功 1.5s
```
接口侧：`/v1/models` 无 key 401、旧 key 401、新 key 200；`/docs` 无 key 401、带 key 200；
带新 key 真出图（768²/12 步/4.2s）。

### 文档
- `docs/API.md`：鉴权一节重写，加入 `QWEN_UI_KEY` 三态表与"地址+key 一起外传等于没设防"的提示。
- `docs/SHARE.md`：第 1 节改成「分享前必做：把 key 模式改成 auto」，
  给了打镜像前换 key 的一行命令，并说明 JupyterLab 侧 token 与 `qwen_env.sh` 里能读到 key 的风险。
- 文档与脚本里的硬编码 `1730` 全部换成 `<你的KEY>` 占位符（CHANGELOG 里的保留，属历史记录）。

## 2026-09-26（下午 · 第八批）· 上线 + 镜像分享准备

### 部署与验证（全部实测）
- 上传并重启服务，**真实进度上线**：20 步请求采样 18 次，步数单调递增 1→20，
  每步 0.512s，ETA 11.2s→0.5s 收敛，`total_s` 11.0s、`callback_ok=True`，结束显示 **100%**。
- 公网入口复验：`/` 200（23270 B）、`/health` 200、`/v1/progress?key=` 200、`/docs?key=` 200。
- JupyterLab 侧确认能识别笔记本：`/jupyter/api/contents/qwen-image-2.1/service/ui` 列出
  `Qwen-Image-2.1-console.ipynb`（notebook / 26654 B / writable），API 读到 nbformat 4、18 格、8 code 格。

### 输出目录盘点（远端 → 本地）
远端 `/root/qwen-image-2.1/outputs` 只有 5 个文件（13 MB），**没有测试期的杂图残留**：

| 文件 | 大小 | 说明 |
|---|---|---|
| `00_acceptance_lantern.png` | 1.42 MB | 本次验收图（1024²/24 步/13.2s/seed 99） |
| `bench_1024_20steps.png` | 1.47 MB | 性能基准 |
| `smoke_512.png` | 0.47 MB | 首轮冒烟 |
| `t2i_2048_40steps.png` | 5.65 MB | 原生 2K 样张 |
| `input_edit_1696x2528.jpg` | 3.61 MB | 编辑用输入图 |

已全部下载到 `test-data/remote_outputs/`（12.62 MB，5/5）。
另外 `/root/qwen-image-2.1/inputs/` 是空的（已建），`/tmp/in.png` 是早期冒烟留下的 760 B 临时文件。

### 镜像分享相关
- **关键约束**：AutoDL 镜像只含系统盘，不含数据盘 → **33 GB 权重不进镜像**，
  别人开新实例必须重下（20~40 分钟）。系统盘只用 601 MB / 30 GB，代码和出图都会进镜像。
- 新增 `docs/SHARE.md`（也放到远端 `/root/qwen-image-2.1/SHARE.md`）：
  保存镜像的步骤与清理项、分享给别人的「一条命令」说明、端口一览、鉴权与改 key、
  性能参考、5 条已知坑。
- `bootstrap.sh` 重写为**首次开机一键初始化**：报环境 → 查/补依赖 → **查权重，缺了自动下载**
  → 起服务并等就绪 → 打印入口。支持 `SKIP_START=1` / `SKIP_DOWNLOAD=1` 做 dry-run 体检。
  dry-run 实测全绿（依赖 8/8、权重 7 分片 33.12 GB、管线类 QwenImage21Pipeline）。
- `show_url.sh` 修掉一个误导：容器内**经代理**访问公网入口返回 403 会被误读成服务挂了。
  现在改成「DNS 解析 + 打本机回环 + 标注哪些端点免鉴权/需要 key」。

### 其他修复
- 笔记本改名为 ASCII `Qwen-Image-2.1-console.ipynb`：中文文件名经 SFTP 传输会变乱码，
  远端出现过一个乱码副本，已删除。生成器/校验器同步改名。
- `show_url.sh` 里的 `✓` 换成 ASCII：Windows 控制台 GBK 输出会抛 UnicodeEncodeError。
- 释放显存缓存：`empty_cache` 后空闲 16.5 G（调后 `reserved` 30.43 G，权重常驻不变）。

## 2026-09-26（下午 · 第七批）· 真实进度 + Jupyter 控制台

### 真实步进进度（替换掉原来按时间猜的假进度条）
后端 `service/server.py`：
- 把管线参数 `callback_on_step_end` 挂上去（`inspect.signature` 探测是否支持，
  不支持就自动去掉并置 `callback_unavailable=true`），每一步记录：
  步号、每步耗时、滑动均值、已用时间、ETA、百分比、最小/最大步耗时。
- 新增 `GET /v1/progress`（最近任务）与 `GET /v1/progress/{request_id}`；`/health` 里也带 `active`。
- 请求可自带 `request_id`（JSON 字段 / form 字段 / `X-Request-Id` 头），响应回 `X-Request-Id`；
  异步任务的 `job_id` 同时就是它的 `request_id`。
- 响应新增 `data[0].timing`：`total_s / prep_s / steps / per_step_s / durations[] / callback_ok`。
- `prep_s` 单独计（显存回收等一次性开销），避免污染"每步耗时"。

前端 `service/ui/index.html`：
- 进度面板从"假的百分比条"换成：`已走 N / M 步` + 百分比 + 进度条 +
  **已用 / 每步 / 预计剩余** 三个数字 + 一行说明（还剩几步、实测每步区间）。
- 数据源是 600ms 单向轮询 `/v1/progress`（同一时刻只允许一个请求在飞）；
  轮询器在 `finally` 里关掉，且不依赖任何可能被重建的 DOM 节点。
- 完成后的日志改成带每步耗时与准备开销。

**实测**（1024×1024 / 20 步 / 4090-48G）：步数单调递增 1→20，每步 0.50~0.51s，
`eta_s` 13.2s → 0.5s 收敛，`total_s` 10.98s，`prep_s` 0.0s。

### JupyterLab 一键控制台
- 新增笔记本 `service/ui/Qwen-Image-2.1-控制台.ipynb`（18 格 / 8 代码格），
  9 节：启动重启服务、打开 WebUI（走 `/jupyter/proxy/6006/`）、端口与入口一览、
  输出目录缩略图预览、直接调 API 出图、实时进度监视、上传图片、**API 速查**、常见问题。
- 兼容性处理：Jupyter 的按钮注入各版本行为不同，因此每个按钮都带 clipboard 兜底，
  并且**每个功能都有一个"改 ACTION 再运行"的稳定入口**——不依赖按钮也能用。
- 生成器 `tools/make_notebook.py`（改内容改它，别手改 .ipynb）、
  校验器 `tools/check_notebook.py`（JSON 可解析 + 每个代码格语法检查 + 必需内容检查）。

### 文档
- `docs/API.md` 新增 3.9 节「进度接口」；错误码表补 404（request_id）；
  第 6 节改为「JupyterLab 控制台 + 命令行客户端」；`QWEN_TILE_VAE` 标注为 2K 必开。

### 待办（未执行）
- 盘点远端 `outputs/` 并把图片下载到本地（脚本已写好放 `remote/scripts/_list_outputs.sh`，
  等确认再跑）。

## 2026-09-26（下午 · 第六批）· 修复「生成按钮卡死」

### 现象
跑完一张图（或任意一次失败）之后，控制台的「生成」按钮永久变灰、点不动，只能刷新页面。

### 根因（无头浏览器里复现出来的）
`service/ui/index.html` 的 `run()` 里有两处**在 `try` 之外**的 DOM 操作：

```js
$('prog').style.width = '0%';   // #prog 每次生成都会被 innerHTML 整块重建
const tick = setInterval(...)   // 同样在 try 之外
```

一旦并发点击 / 上一次请求失败导致这两处的引用取到 `null`，就会抛
`Cannot read properties of null (reading 'style')`——**异常发生在 try 之外，
所以 `finally` 里的复位代码根本不会执行**，`busy` 永远停在 `true`、
`$('run').disabled` 永远是 `true`。

复现证据（探针在无头浏览器里连点两次后）：

```
S2 BEFORE  busy=false disabled=false
PAGE unhandledrejection: Cannot read properties of null (reading 'style')
S2 AFTER   busy=true  disabled=true      ← 之后 S3/S4 全部起不来
```

### 修复
- 进度条改成 `setProg()` 内部每次自查元素是否存在（元素会被重建）。
- `setInterval` 移进 `try`，句柄可空。
- `finally` 里所有清理都包上 try 保护：**这里再抛异常就会把按钮永久锁死**。
- 按钮元素改成先取变量再判空。
- 顺便加了 `_archive` 的探查脚本（用完即删）：`ui_button_probe.py`（注入探针 + 包装 fetch
  记录每次请求）、`tunnel_post_probe.py`（隧道 POST 能力验证）。

### 修复后实测（无头浏览器，隧道链路）
| 阶段 | 结果 |
|---|---|
| S1 正常生成 512×512 / 4 步 | 200 · 1.1s · 图片显示 · **按钮已复位** ✅ |
| S2 连续点击两次 | 只发出 1 个请求（第二次被 `busy` 挡掉）· 按钮已复位 ✅ |
| S3 故意用错 key | 401 · 页面提示友好 · **按钮仍复位** ✅ |
| S4 失败后立即重试 | 200 · 0.9s · 出图 ✅ |

线上页面（公网入口与隧道）已确认是修复后的版本。

### 排查过程中顺带确认
- 隧道 POST 通道本身没问题（Python 直测 200、526KB）：
  `tunnel_post_probe.py` 验证了带 header 的 key 和 `?key=` 两种方式都能过。
- 第一次复现时看到的 "Unexpected end of JSON input" 是**测试壳子自己的 bug**——
  壳子服务的端口与隧道端口不同，页面按 `location.origin` 推 API 地址时打回了壳子自己（204 空响应）。
  修法是注入时把 `const ROOT = ...` 改写成真实服务地址。生产环境不存在这个问题
  （页面本来就由服务自己提供，同源）。

## 2026-09-26（下午 · 第五批）· 本机访问隧道

### 新增
- `tools/tunnel_serve.py`：用 paramiko 做本地端口转发（只依赖 paramiko，不用系统 ssh.exe）。
  读同目录 `tunnel.conf`，命令行可覆盖任意参数；关掉窗口/进程即断开。
- `tools/tunnel.conf`：实例连接信息 + `local_port=16006` + `remote_port=6006`。
- `tools/qwen-tunnel.bat`：双击即用。建隧道 → 4 秒后自动打开
  `http://127.0.0.1:16006/` → 检测到端口已占用则直接开浏览器不重复建。
  找不到 paramiko 时自动退回 `ssh.exe`（会提示输密码）。
- 桌面快捷方式 **「Qwen 控制台」** → 指向上面的 .bat（工作目录设为 `tools\`，
  所以相对路径的 `tunnel_serve.py` / `tunnel.conf` 都能找到）。
- `tools/tunnel_test.py`：隧道链路自检（HTTP 探测 + 真出图 + 隧道地址截图）。

### 排障记录：为什么放弃了 SSH 密钥登录
- 在实例 `/root/.ssh/authorized_keys` 里装了 ed25519 和 RSA 两把公钥，权限（700/600）、
  sshd 配置（`pubkeyauthentication yes`、`strictmodes yes`、`authorizedkeysfile .ssh/authorized_keys .ssh/authorized_keys2`）
  全部核对无误。
- 现象：服务端日志出现 `Server accepts key`（密钥被接受），紧接着
  `Permission denied (publickey,password)`。
- `ssh -vvv` 显示客户端用的是 `sign_and_send_pubkey: using publickey-hostbound-v00@openssh.com`：
  Windows 自带 **OpenSSH 9.5p2** 与服务端 **OpenSSH 8.9p1 (Ubuntu)** 在 host-bound 签名扩展上不兼容。
  试过 `PubkeyAcceptedAlgorithms=ssh-ed25519`、换 RSA-3072、`ServerAliveInterval` 等组合，均失败。
- 结论：走 paramiko 密码通道（实测稳定），并保留 `tunnel.conf` 的 `key=` 字段供将来切换。
  两把备用公钥仍留在实例的 `authorized_keys` 里，不影响密码登录。

### 验证
| 项 | 结果 |
|---|---|
| `python tunnel_serve.py` 起隧道 | 127.0.0.1:16006 → 远端 6006 ✅ |
| 隧道内 `/health`、`/`、`/v1/models?key=1730` | 200 / 200(18597B) / 200 ✅ |
| 隧道内不带 key 请求 `/v1/models` | 401 ✅ |
| 隧道地址下无头浏览器渲染 WebUI | 正常 → `reports/webui-tunnel.png` ✅ |
| 双击 `qwen-tunnel.bat`（cwd=tools） | 隧道建立 + 端口探测全绿 ✅ |

## 2026-09-26（下午 · 第四批）· 接口鉴权

### 新增
- `QWEN_API_KEY`（默认 `1730`，写在 `qwen_env.sh`）：`/v1/*`、`/docs`、`/redoc`、`/openapi.json`
  全部需要 key；`/`（控制台）、`/ui`、`/health` 不设鉴权，否则页面打不开、存活探测也做不了。
- 两种带法等价：`Authorization: Bearer <key>` 与 `?key=<key>`（后者给浏览器跳转/`<img>`/`<a>` 用）。
- 控制台新增「API Key」输入框，值由服务端渲染时注入（`__QWEN_KEY_INJECT__` 占位符 → `QWEN_API_KEY`），
  所以改 key 只需改服务端环境变量，页面自动同步，不用改前端代码。页面内所有请求都会带 key。
- `serve.sh start` 会打印鉴权是否开启；`show_url.sh` 顺带提示入口。

### 修复（自测时发现的坑）
- **`/v1/models` 原来根本没接鉴权**：第一版实现只在需要 request 对象的处理器里手动调
  `_check_auth`，`/v1/models` 没有被调用，无 key 也是 200。
  改成 FastAPI 依赖统一守卫（`dependencies=[Depends(require_key)]`），8 个路由全部挂上，
  以后新增路由漏挂会一眼看出来。
- **内置 `/docs` 抢在自定义路由前面**：自定义的受保护 docs 因为 `app = FastAPI()` 时
  内置端点已注册，永远不生效（无 key 也 200）。改为 `FastAPI(docs_url=None, redoc_url=None,
  openapi_url=None)` 关掉内置的，再用 `get_swagger_ui_html` / `get_openapi` 自己实现，
  Swagger 的 `openapi_url` 里直接带上 key，这样 `?key=xxx` 打开后文档能正常加载。

### 验证（本机 → 公网入口）
| 请求 | 结果 |
|---|---|
| `/health`、`/` 无 key | 200（按设计放行） |
| `/v1/models` 无 key / 错 key | **401** |
| `/v1/models` `Bearer 1730` | 200 |
| `/v1/models?key=1730` | 200 |
| `/docs` 无 key | **401** |
| `/docs?key=1730` | 200 |
| `/` 页面注入 | `id="apikey" value="1730"` ✅ |
| 公网 512×512 / 8 步真出图（带 key） | OK |

截图：`reports/webui-public.png`（可见 key 已自动填好）。

### 说明
- 4 位数字是弱口令，只挡扫端口的陌生人，不挡有心人。公网入口别外传。
- 页面自身不设鉴权（否则打不开）且会回显 key —— 能打开页面的人本来就能用这个服务，
  这个取舍是刻意的；要更严就换随机长 key。

## 2026-09-26（下午 · 第三批）

### 新增：公网入口查询脚本
- `service/show_url.sh`（远端 `/root/qwen-image-2.1/scripts/show_url.sh`）：
  **AutoDL 把公网映射地址写在容器的 `/init/others/help` 里**，不必去控制台翻。脚本会打印
  `AutoDLService6006URL` / `AutoDLService6008URL`，并对 `/` `/health` `/docs` 逐一做入口自测，
  最后给 SSH 隧道的替代命令和服务进程状态。
- 本实例实测入口：`https://<实例ID>.westb.seetacloud.com:8443`（6006），
  备用 6008 为 `https://<端口6008前缀>-<实例ID>.westb.seetacloud.com:8443`（两个域名指向同一容器）。
- 经公网入口复验：`/` 17690 字节 · `/health` 258ms · `/docs` · `/v1/models` 全部 HTTP 200，
  并用无头浏览器在该公网地址上截图确认渲染正常 → `reports/webui-public.png`。

### 说明
- 端口映射是平台侧的东西，容器内无法自行创建；`/init/others/help` 是读取入口的官方来源。
- 服务绑 `0.0.0.0:6006`（uvicorn 日志确认），用容器内网 IP `172.17.0.1:6006` 也能访问。

## 2026-09-26（下午 · 第二批）

### 新增：浏览器控制台（WebUI）
- `service/ui/index.html`：单页控制台，挂在服务根路径 `/`（别名 `/ui`），无构建步骤、不依赖 Gradio。
  文生图 / 图像编辑切换、prompt、宽高与官方宽高比档位、步数滑杆、seed、透明 RGBA、
  异步排队、编辑专用 `output_resolution`；右侧显示耗时/尺寸/seed/峰值显存，支持下载、
  复用参数、会话内历史（缩略图可点开）。
- `service/server.py`：新增 `GET /` 与 `GET /ui` 返回控制台；`GET /favicon.ico` 返回 204；
  加 `CORSMiddleware`（放开跨源，方便别的页面/工具直接调接口）。
- `tools/webui_check.py`：端到端自检——开 SSH 隧道 + 无头浏览器真跑一次出图，
  校验「页面加载 → /health → 真实生成」并留下截图。
- `tools/webui_shot.py`：只出截图（headless 视口不听话时注入样式钉死桌面布局后截图）。

### 修复
- **控制台的左栏整块不显示**：`setMode()` 里用 `el.parentElement.style.display` 隐藏元素，
  把整个 `.panel` 一起藏了（诊断脚本量出 `leftRect.height = 0`）。
  改为给 `negwrap` / `outreswrap` 各自包一层容器再切换 display。
- 端到端自检里发现接口没有 CORS 头，跨源包装页 fetch 全被浏览器拦掉 → 已加中间件。

### 验证
- `tools/webui_check.py` 实测通过：`health loaded=true`、页面 16977 字节、标题正确、
  `POST /v1/images/generations` 1024×1024 / 12 步 **7.8s** 出图成功。
- 截图产物：`reports/webui-preview.png`。

## 2026-09-26（下午）

### 新增
- `tools/dress_shell_test.py` + `docs/CASE-dress-shell.md`：专项案例「连衣裙花纹 → 贝壳」。
  三条措辞变体全部成功，其中 S2（强调只改印花）配色最准确；数据与对照图在 `test-data/case_shell/`。
- 该案例修正了指令矩阵的结论：**局部"纹理/图案"替换能执行，局部"语义"改动不能**，两者要分开看。
- 方法学补充：局部纹理改动的验收必须**限区域量化 + 目视**——全图指标完全分辨不出
  （基线 0.0679 vs 贝壳版 0.0739，差 9%），裙子区域才能看出来（0.0801 → 0.1010，高出 26%）。

### 文档
- `docs/MEASUREMENTS.md` 增加 7.1 节（局部纹理替换案例与修正后的响应分类）。
- `docs/CASE-dress-shell.md`：完整案例记录（步骤、量化、产物、复现命令）。

## 2026-09-26（上午）

### 目录整理
- 新建顶层目录 `qwen-image-2.1-tools/`，把此前散落在 `tools/`、`tools/qwen_service/`、
  `tmp/qwen_test/` 下的脚本、文档、测试产物全部归拢进来：
  - `service/` —— 服务与库（server / client / face_fix / bench / inspect_ckpt / qwen_env.sh）
  - `remote/scripts/` —— 实例上用的运维脚本 + 部署期一次性探测脚本（`_*.sh`）
  - `tools/` —— 本机测试与报告脚本，新增 `config.py` 统一路径
  - `test-data/` —— 全部测试产物（97 个文件，221 MB）
  - `reports/` —— HTML 报告
  - `docs/` —— README / API / MEASUREMENTS / CHANGELOG
- 脚本内的硬编码路径改成 `import config as C` 或相对 `__file__` 推导，
  换目录/换机器不用改代码。

### 新增功能
- `tools/run_tunnel.py`：一条命令建立 SSH 端口转发并在其内部运行指定测试脚本
  （脚本里用注入的全局 `BASE` 指到转发端口）。
- `tools/matrix_test.py` + `tools/matrix_report.py`：16 条指令的响应矩阵测试与 HTML 报告。
- `tools/config.py`：集中路径与区域定义（face / torso / border / figure 四个归一化区域）。

### 服务端（`service/server.py`）
- 新增 `output_resolution` 参数（edits 接口），这是控制去噪分辨率与输出边长的真正旋钮；
  `width`/`height` 在编辑路径上会被模型忽略。
- 新增 `POST /v1/admin/empty_cache`：把分配器缓存还给驱动。长跑进程会攥住十几 GB 不放，
  跑 2K 之前建议先调一次。
- 每次生成前自动 `empty_cache()`，再做显存预检——修正了"预检把常驻权重算进去"导致所有请求误判 507 的 bug。
- `/health` 增加 `preload` / `load_error` / `peak_allocated_gib`。
- `QWEN_MODE` 三态：`auto`（无卡自动降级为占位图）/ `real`（无卡直接 409）/ `mock`。

### 修复
- `_queue_depth` 作用域 bug：`generations` / `edits` / `create_job` 里 `+=` 会让它变成局部变量，
  导致 `UnboundLocalError` 使服务完全起不来。
- FastAPI `on_event("startup")` 换成 `lifespan` 上下文管理器，消除弃用警告。
- 显存预检逻辑重写：只比较本次运行的"临时开销"与真实空闲显存，
  并在预检前 `empty_cache()`（否则缓存块会让可用显存看起来只有 6 GiB）。
- `face_fix.locate()` 重写：放弃自动定位（Haar / 模板匹配 / 肤色三种方案实测均不可靠），
  改为固定位置贴回 + 局部相关置信度闸门；贴回区域越界时安全跳过而不是贴错。
- 所有 JSON 落盘显式 `encoding="utf-8"`（中文 Windows 默认 GBK，会直接崩）。
- `serve.sh` 增加 `restart` 动作，并默认导出 `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`。

### 实测结论（写入 docs/MEASUREMENTS.md）
- 指令响应有明确强弱分层：背景/服装/画风/姿势/多指令可靠；表情、单物体增删不可靠。
- 空指令基线与输入图的 MAD 为 0.104 —— "重绘整图"是这个模型的默认行为。
- 编辑链每步都会重画脸，人脸漂移与整图漂移同量级；提示词措辞对保持率零影响。
- 2048² 必须开分块 VAE，否则 OOM 在 VAE 上采样层。

### 待办
- 手部专项测试（手指崩溃的姿势边界）。
- 多 seed 批量筛选 + 自动挑图（用 `/v1/jobs` 异步）。
- 人脸回贴的自动化定位：考虑引入 rembg 主体分割或人体关键点模型。
- 两个一次性脚本 `qwen_test_round1.py` / `qwen_test_round2.py` 在目录整理时误删（内容是文生图+编辑的首轮
  验收脚本，已被 `qwen_chain.py` 与 `qwen_pose_test.py` 覆盖），需要时照 `docs/MEASUREMENTS.md` 第 2 节重建。

### 备注
- `tools/autodl.env` 与 `tools/autodl2.env` 含实例 SSH 凭据，仅本机使用，不要外发或提交到公开仓库。

