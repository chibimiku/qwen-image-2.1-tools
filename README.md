# qwen-image-2.1-tools

Qwen-Image-2.1（7B DiT + Qwen3-VL 8B 编码器 + RGBA VAE）在 AutoDL 上的部署、封装与能力实测工具箱。
所有结论都是在**真实机器 + 真实权重**上跑出来的，不是估算表。

```
2026-09-26 起   AutoDL 西部 B 区 · RTX 4090 48G（魔改，单卡，sm_89）
镜像           PyTorch 2.8.0 + cu128 + Python 3.12.3
权重           /root/autodl-tmp/Qwen-Image-2.1  共 33.13 GB
依赖           transformers 5.17.0 · diffusers 0.41.0.dev0(git main) · accelerate 1.15.0
```

---

## Prompt 写法（给使用者和后续 AI）

**官方有 prompt 编写指导。** Qwen-Image-2.1 官方仓库建议用配套的 Prompt Rewriting（PE）模型，
把简短需求扩写成清晰、可执行的指令；官方同时公开了 T2I 与图像编辑的完整 system prompt。
参见 [官方 Prompt Rewriting 说明](https://github.com/QwenLM/Qwen-Image-2.1#prompt-rewriting)、
[官方编辑 system prompt](https://github.com/QwenLM/Qwen-Image-2.1/blob/main/prompt_rewrite/prompts/system_prompt_edit.txt)，
仓库内的固定副本见
[`docs/upstream/prompt-rewriter-I2I-system-prompt.txt`](docs/upstream/prompt-rewriter-I2I-system-prompt.txt)。

### 本项目最常用的模板：让参考图主角去做一件事

适用于“让给定图片里的主角在某处做某事”，例如在夜空下的天台浇花：

```text
将图像中的主角置于【场景】，让主角正在【核心动作】。
【用一两句写清手脚姿态、主体与物体的接触关系，以及动作进行到哪一步】。
场景中有【与动作直接有关的物体和环境】，时间为【时间/天气】，由【主光源】照明，呈现【气氛】。
使用【景别、视角和构图】，确保【动作所需的身体部位和关键物体】清楚、完整、归属明确。
保持主角身份、标志性配饰和原图视觉媒介不变；未指定内容自然延续。
```

可直接使用的例子：

```text
将图像中的主角置于夜空下的城市天台，让主角正在给一排花盆浇水。主角微微俯身，
一只手握住浇水壶把手，另一只手托住壶身，清晰的水流落入最近的花盆。天台摆放少量绿植，
远处是城市灯光与深蓝色夜空，月光作为柔和轮廓光。使用中景、略低机位的三分构图，
确保主角的双手、浇水壶、水流和花盆清楚完整、彼此关系明确。保持主角身份、标志性配饰
和原图视觉媒介不变；未指定内容自然延续。
```

宽高比不要写进 prompt；在 UI 的尺寸/比例控件中单独选择。上述横向环境叙事可先试 `3:2`，
突出人物全身可先试 `3:4`。

### 后续 AI 编写 prompt 的约束

后续 AI 在本项目里生成或改写“参考图主角做某事”的 prompt 时，**应优先套用上面的模板**，并遵守：

1. **操作开头**：先写“将/把图像中的主角置于……，让其……”，不要先堆成品形容词。
2. **动作必须可观察**：写清哪只手拿什么、身体朝向、人与物如何接触；复杂动作要减少无关要求。
3. **主动构建新场景**：这是“用参考图身份生成新画面”，应补足场景、光线、镜头和构图；局部编辑则只写改什么。
4. **保持项只概括一次**：不要逐项复述主角的脸、头发、体型和服装细节。官方指出，过度描述本应保持的外观，反而会让模型重新生成并降低身份一致性。
5. **用肯定句**：写“主角双手和浇水壶完整入镜”，少写“不要裁切、不要多手”之类否定句。
6. **不凭空发明**：只依据参考图中可见内容；不确定的外貌或配饰不补写。
7. **图片编号**：单张参考图自然写“图像中的主角”，不要写 `<image1>`；两张及以上时按上传顺序使用 `<image1>`、`<image2>`，并明确每张图提供什么。
8. **尺寸与指令分离**：prompt 中不写 `2K`、`1920×1080` 或 `3:2`，尺寸交给 UI/API 参数。

这套规则来自官方编辑 PE 的核心原则：根据意图区分局部修改与新场景构建、锚定输入图、保持项不要
重新描画、身份通过参考图指代、操作放在句首、多图必须使用 `<imageN>`。复杂姿态和人体异常的专项写法
另见 [`docs/PROMPT-ANATOMY.md`](docs/PROMPT-ANATOMY.md)。

---

## 部署（给 agent 的执行说明）

> 目标：**跑完之后 `curl 127.0.0.1:6006/health` 返回 `"loaded": true`。**
> 本节列出的每条命令都可直接执行。先读完「前置条件」再动手，缺东西要**先问用户**，别猜。

### 前置条件

| 需要什么 | 谁提供 | 没有的话 |
|---|---|---|
| 一台 AutoDL 实例，**显存 ≥ 40 GB**（实测 48G 卡能全 BF16 常驻） | 用户 | 停下来问用户要实例 |
| 实例的 **SSH 域名 / 端口 / root 密码**（AutoDL 控制台 → 容器实例 → SSH 登录指令） | 用户 | 停下来问用户要 |
| 本机 Python 依赖：`paramiko`（部署要）、`pillow` / `requests`（测试要） | `pip install paramiko pillow requests` | 直接装 |
| 33 GB 磁盘放权重（AutoDL 上是 `/root/autodl-tmp`，系统盘只有 30 G，**不要放系统盘**） | 实例自带 | 见步骤 2 的说明 |

> ⚠️ **权重不在这个仓库里**。仓库只有服务端（约 0.9 MB），
> 33 GB 的模型权重由步骤 2 的 `bootstrap.sh` 自己下载（20~40 分钟）。
> 如果用户已经有一台装好权重的实例，跳过下载即可，脚本会自动检测。

### 步骤 0 · 确认在正确的位置

```bash
cd <repo>            # 仓库根目录，能看到 service/ 和 tools/
python -c "import sys; print(sys.version)"   # 3.10+ 即可
```

### 步骤 1 · 传服务端（本机执行，约 3 秒）

```bash
pip install paramiko

# 首次：带上连接信息，顺手存进 tools/autodl.env（该文件 git-ignored，不会进仓库）
python tools/deploy_service.py \
  --host <实例域名> --port <端口> --password '<root 密码>' --save-env

# 之后（凭据已在 tools/autodl.env）：一条命令，幂等，只传有变化的
python tools/deploy_service.py
```

**这一步做到什么**：把 `service/` 整棵树镜像到实例的 `/root/qwen-image-2.1/`。
15 个文件，比 md5 跳过没变的。

**不要**加 `--force-env`：实例上的 `qwen_env.sh` 存着**真实 API Key**，
仓库里那份是 `CHANGE_ME` 占位符，覆盖过去会让服务变成 401。

期望输出结尾：

```
完成：传输 N / 跳过(相同) M / 保护 1
提示：远端 qwen_env.sh 保持原样，实例上的 key 没被被动过。
```

### 步骤 2 · 装依赖 + 下权重 + 起服务（实例上执行，20~40 分钟）

```bash
ssh -p <端口> root@<实例域名> 'bash /root/qwen-image-2.1/scripts/bootstrap.sh'
```

这一步是**幂等**的，会依次做 5 件事：检查系统信息 → 装 pip 依赖 → 校验/下载权重
→ `serve.sh start` → 打印公网入口。

几个必须知道的点：

- **`python-multipart` 必须装上**，否则上传参考图的请求全部 400。`bootstrap.sh` 里已经包含。
- **`QWEN_TILE_VAE=1` 是硬需求**：不开的话 2048² 会崩在 VAE 上采样层。
  `qwen_env.sh` 与 `serve.sh` 都设了默认 1 —— 所以**永远不要绕过 `serve.sh` 直接
  `python service/server.py`**。
- 长时间下载建议挂后台，别让 SSH 断掉：
  ```bash
  ssh -p <端口> root@<实例域名> \
    'nohup bash /root/qwen-image-2.1/scripts/bootstrap.sh > /root/bootstrap.log 2>&1 & echo started'
  # 看进度
  ssh -p <端口> root@<实例域名> 'tail -20 /root/bootstrap.log'
  ```
- 权重下到一半断了：`bash /root/qwen-image-2.1/scripts/watch_download.sh` 是看门狗，会自动重拉。

> **没有 `ssh` 客户端 / 不方便交互输密码？** 用仓库自带的 SSH 驱动代替上一条命令，
> 凭据同样从 `tools/autodl.env` 读：
>
> ```bash
> python tools/autodl_run.py "bash /root/qwen-image-2.1/scripts/bootstrap.sh"
> ```
>
> 但这条是**前台执行**，SSH 一断就跑不完。要挂后台：
>
> ```bash
> python tools/autodl_run.py "nohup bash /root/qwen-image-2.1/scripts/bootstrap.sh > /root/bootstrap.log 2>&1 & echo started"
> python tools/autodl_run.py "tail -20 /root/bootstrap.log"
> ```

### 步骤 3 · 验证（必须做，别跳过）

```bash
# 3.1 服务活了吗（真实进度的唯一可信判据）
ssh -p <端口> root@<实例域名> "curl -s localhost:6006/health"

# 3.2 仓库提交的版本 == 实例上跑的版本
python tools/check_deploy.py

# 3.3 出图自测：1024²/20 步，约 11 秒
python tools/autodl_ssh.py run \
  "curl -s -X POST localhost:6006/v1/images/generations \
     -H 'Authorization: Bearer <key>' \
     -F prompt='a red cube on a white table' \
     -F num_inference_steps=20 -F width=1024 -F height=1024 | head -c 200"
```

**验收标准**：

| 检查 | 通过的样子 |
|---|---|
| 3.1 | `{"status":"ok",...,"loaded":true,...}` |
| 3.2 | `一致 15 / 不一致 0 / 仓库缺 0 / 远端无 0` |
| 3.3 | 返回 JSON，里面有 `"b64_json"` |

`<key>` 从哪来：实例上 `grep QWEN_API_KEY /root/qwen-image-2.1/qwen_env.sh`。
WebUI 则直接开 `http://<实例公网入口>/`，页面上输一次 key 就换成 HttpOnly Cookie 会话。

### 卡住了怎么办

| 症状 | 原因 | 处理 |
|---|---|---|
| `缺少连接信息` | 没给 `--host/--port/--password`，也没有 `tools/autodl.env` | 回到步骤 1，加 `--save-env` |
| `Authentication failed` | 密码错，或本机 OpenSSH 太新而服务端太老 | 工具已内置 RSA-SHA2 回退；仍失败就问用户核对密码 |
| 上传参考图报 **400** | 实例缺 `python-multipart` | `pip install python-multipart` 后重启服务 |
| `/health` 里 `loaded: false` | 权重还在加载（约 2 分钟）或是下载没完成 | 等；`tail /root/qwen-image-2.1/logs/service.log` |
| 2048² CUDA OOM | 没开分块 VAE 解码 | 确认用 `serve.sh` 启动，且 `qwen_env.sh` 里 `QWEN_TILE_VAE=1` |
| 所有 `/v1/*` 都 401 | 步骤 1 误用了 `--force-env`，把 key 覆盖成占位符 | 从备份或用户处取回 key，写回实例 `qwen_env.sh` 后重启 |
| `check_deploy.py` 报 `一致*` | `qwen_env.sh` 只有 key 值不同 | **正常**，这是设计使然 |

### 更多细节

每个文件映射到哪、为什么这么定、`qwen_env.sh` 的占位符策略 —— 见 **[docs/DEPLOY.md](docs/DEPLOY.md)**。
接口定义见 **[docs/API.md](docs/API.md)**。

---

## 目录结构

| 目录 | 内容 |
|---|---|
| `docs/` | **[docs/README.md](docs/README.md) 总说明** · [DEPLOY.md](docs/DEPLOY.md) **部署（目录映射 + 三步）** · [API.md](docs/API.md) 接口定义 · [RESOLUTION.md](docs/RESOLUTION.md) **分辨率与尺寸怎么选（含 token 经济账）** · [PROMPT-ANATOMY.md](docs/PROMPT-ANATOMY.md) **人体崩坏怎么优化** · [CFG-NEGATIVE-AB-TEST.md](docs/CFG-NEGATIVE-AB-TEST.md) **CFG/负面词的多 seed 盲测方案** · [CFG-NEGATIVE-AB-RESULTS.md](docs/CFG-NEGATIVE-AB-RESULTS.md) **该方案的执行结论：不建议用 CFG** · [METADATA.md](docs/METADATA.md) **生成图元数据（PNG 内嵌 / 模型与图片 hash）** · [MEASUREMENTS.md](docs/MEASUREMENTS.md) 全部实测数据 · [SHARE.md](docs/SHARE.md) **镜像保存与分享** · [CASE-dress-shell.md](docs/CASE-dress-shell.md) 专项案例 · [CHANGELOG.md](docs/CHANGELOG.md) 改动记录 |
| `docs/upstream/` | **官方文档本地副本**（GitHub README / HF 模型卡 / ModelScope / LICENSE / diffusers 管线源码），索引见 [docs/upstream/INDEX.md](docs/upstream/INDEX.md)。同步：`python tools/sync_upstream_docs.py` |
| `service/` | **= 部署载荷**，结构与实例 `/root/qwen-image-2.1/` 一一对应。`server.py` HTTP 服务 · `client.py` 调试客户端 · `face_fix.py` 人脸回贴 · `ui/` 控制台 · `scripts/` 启停与环境脚本 |
| `service/scripts/` | `serve.sh` 启停 · `bootstrap.sh` 一键恢复 · `qwen_env.sh` 环境变量 · `download_model.sh` 下权重 · `download_anatomy_model.sh` 下人体复检小模型（可选） · `bench.py` / `inspect_ckpt.py` / `show_url.sh` |
| `tools/` | 本机工具：`deploy_service.py` **部署** · `check_deploy.py` **对账** · `autodl_run.py` / `autodl_ssh.py` SSH 驱动 · 测试与报告生成 · `scan_secrets.py` 提交前扫描 |
| `remote/scripts/` | 只在实例上跑的一次性脚本：部署期探测、实验、巡检（`_*.sh`） |
| `test-data/` | 全部测试产物：输入图、每轮输出、量化 JSON、接触表（体积大，未入库） |
| `reports/` | 生成的 HTML 报告（单文件、图片内嵌，可直接外发）（未入库） |

---

## 实例上怎么操作（已部署好之后）

```bash
# 启停
bash /root/qwen-image-2.1/scripts/serve.sh start|stop|restart|status|fg

# 环境变量（端口、key、tile_vae、offload 都在这里）
source /root/qwen-image-2.1/qwen_env.sh

# 看公网入口
bash /root/qwen-image-2.1/scripts/show_url.sh

# 日志
tail -f /root/qwen-image-2.1/logs/service.log
```

---

## 本机快速开始

```bash
# 起隧道（把远端 6006 映射到本地 16006）
python tools/run_tunnel.py <某个测试脚本>.py

# 或者直接看服务状态
python tools/autodl_ssh.py health          # 读 tools/autodl.env 里的实例信息
python tools/autodl_ssh.py run "nvidia-smi"
```

---

## 已经跑出来的核心结论

1. **能跑，24s/张（35 步，832×1248）**；1024×1024/20 步只要 10.9s，2048×2048/40 步 115.3s。
   **2048² 必须开分块 VAE 解码**（`QWEN_TILE_VAE=1`），否则在 VAE 上采样层 OOM。
2. **每一步编辑都会重绘整张图，包括脸。** 只改姿势的那一步，人脸区域漂移 0.180 ≈ 整图漂移 0.177；
   提示词里写 KEEP 段落（长句 vs 清单式）数值几乎逐位重合——**措辞锁不住人脸**。
   空指令基线（"什么都别改"）与输入图的 MAD 也有 0.104，说明"重绘"是这个模型的默认行为。
3. **人脸只能靠链路之外补**：`service/face_fix.py` 把源图人脸按羽化椭圆贴回，7 个样本全部改善
   0.029~0.044。但**自动定位人脸不可行**（Haar/模板匹配/肤色连通域三种方案实测全败），
   报告里给了一个浏览器内拖拽框选的手动对齐工具。
4. **指令响应有明确的强弱分层**（见 `reports/matrix-report.html`）：
   - 可靠：背景替换、服装换色/改款、整体画风、姿势改造、多指令叠加
   - 不可靠：表情（笑/哭两张图互相只差 0.004）、单个道具增删、照片写实化
5. **编辑输出尺寸被钉在 1MP 档位**（832×1248 / 1056×1568），真正的旋钮是管线参数
   `output_resolution`；提高它只是让耗时翻倍，不改善保真度。
6. **多参考图引用有官方语法：`<image1>` / `<image2>` …**，编号 = `image` 参数的上传顺序；
   官方 PE 对单张参考图则建议自然写“图像中的主角”，不显式使用标签。
   管线会把这些占位符真的写进文本编码器的 prompt（`prompt_template_ti2i`），
   官方多人物示例（`prompt_rewrite/data/edit_example.jsonl`）用的就是这个写法。
   受控实验显示：**不点名时两个主体会被融成一个，点名后正确分开**。
   详见 [docs/EXPERIMENT-ref-syntax.md](docs/EXPERIMENT-ref-syntax.md)。
   WebUI 上传参考图后，缩略图下方会出现 `<image1>`/`<image2>` 按钮，点一下插到 prompt 光标处。
7. **负面提示词 + CFG 实测不建议使用**（144 张配对实验：3 类任务 × 4 组 × 12 seed）。
   - **耗时翻倍**：1024²/20 步，不开 CFG 11.5s（文生图）/ 13.8s（编辑），开了 22.2s / 26.5s；
     开销与 `true_cfg_scale` 取 2.0 还是 2.5 **无关**。
   - **画面退化**：开了之后整体偏线稿/淡彩，留白多、颜色发灰，完成度肉眼可见地下降。
   - **收益没验证出来**：唯一可用的自动判据（SmolVLM2-2.2B 审图）对插画风格**结构性一律 PASS**
     （模型自己的指令里就写着 `PASS if ... stylized`），测不出"多一条腿"这一档；
     人眼 1:1 逐格复核后，原本怀疑的"多腿"大部分是**把垂在身侧的手臂误判成了腿**。
   - 想改善人体结构，优先走 **prompt 工程**：按官方 PE 方法改写 prompt 的耗时与不改**完全相同**
     （零成本），而 CFG 是双倍成本换一个没验证出来的收益。详见
     [docs/CFG-NEGATIVE-AB-RESULTS.md](docs/CFG-NEGATIVE-AB-RESULTS.md)。

> 第 7 条同时留下一条方法论教训：**fail-open 的工具必须自带"我还活着吗"的探针。**
> 那次实验的自动评分表显示"144 张全部 0% 异常、置信度 0.00"，
> 实际是 144 条 `label` 全为 `unavailable`（断网导致模型没加载，fail-open 默认返回 PASS）。
> 汇总表里"没判过"和"真的没问题"长得一模一样 —— 判据要用 `label`，不是 `passed`。

细节和原始数据见 `docs/MEASUREMENTS.md`，逐步骤图文对比见 `reports/` 下的 HTML。

---

## 文档索引

- [docs/README.md](docs/README.md) —— 环境怎么建的、服务怎么起、测试怎么跑
- [docs/API.md](docs/API.md) —— HTTP 接口完整定义（含错误码、环境变量、上游对接片段）
- [docs/EXPERIMENT-ref-syntax.md](docs/EXPERIMENT-ref-syntax.md) —— 参考图 `<imageN>` 引用语法：源码依据 + 受控实验
- [docs/CFG-NEGATIVE-AB-TEST.md](docs/CFG-NEGATIVE-AB-TEST.md) —— negative prompt / CFG 的多 seed 配对盲测方案
- [docs/CFG-NEGATIVE-AB-RESULTS.md](docs/CFG-NEGATIVE-AB-RESULTS.md) —— **上面那套方案的执行结果与结论**（不建议用 CFG；含两个失效工具的事后复核）
- [docs/UI-AUDIT.md](docs/UI-AUDIT.md) —— WebUI 说明文案与参数选项逐项核查
- [docs/MEASUREMENTS.md](docs/MEASUREMENTS.md) —— 性能表、显存账、每一轮实验的数据与结论
- [docs/CHANGELOG.md](docs/CHANGELOG.md) —— 脚本目录调整、修过的 bug、接口变更
- `reports/matrix-report.html` —— 指令响应矩阵报告
- `reports/face-fix-report.html` —— 人脸补偿 + 表情专项分步对比报告
- [docs/OUTPUTS-INVENTORY.md](docs/OUTPUTS-INVENTORY.md) —— **生成产物清单**（本地产物与实例输出的逐项盘点，含清理命令）

> `test-data/`、`reports/`、`tmp_refs/` 里是约 316 MB 的实验产物，**没有进仓库**（见 `.gitignore`）。
> 需要图就照 `docs/MEASUREMENTS.md` 里的命令重跑，或自己留着本地副本。
> 随时用 `python tools/inventory_outputs.py` 重新盘点、`--write` 更新清单。
