# CHANGELOG

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

