# v1.0.0 — Qwen-Image-2.1 单卡部署工具包

> **定位**：把 Qwen-Image-2.1 跑在**一张 48G 卡**上，并封成可用的 HTTP 服务 + WebUI +
> 一套"踩过坑"的文档。仓库里**不含模型权重**（33 GB 由脚本自己下）。
> 所有结论都在真实机器上实测过，做不到的地方也写在文档里。

## 这个版本能干什么

**一条管线，两个入口都收**

底层只有 `QwenImage21Pipeline` 一个管线：传 `image` 就是条件生成（编辑 / 多主体合成），
不传就是纯文本生成。服务端把这两件事统一到 `POST /v1/images/generations` 一个端点，
`/v1/images/edits` 保留为等价别名。请求体 JSON 与 multipart 两种都收。

**16 个端点**，覆盖从出图到取消的完整链路：

| 类别 | 端点 |
|---|---|
| 出图 | `POST /v1/images/generations`（统一入口，`image` 可选）· `POST /v1/images/edits`（别名） |
| 异步 | `POST /v1/jobs` · `GET /v1/jobs/{id}` · `DELETE /v1/jobs/{id}` · `GET /v1/jobs` |
| 进度 | `GET /v1/progress` · `GET /v1/progress/{id}` · `POST /v1/progress/{id}/cancel` |
| 尺寸 | `GET /v1/fit`（当前显存下这个比例最大能跑多少） |
| 鉴权 | `GET/POST/DELETE /v1/session`（HttpOnly Cookie 会话） |
| 其它 | `GET /health`（免鉴权）· `GET /v1/models` · `GET /v1/admin/empty_cache` · `/docs` |

**鉴权**：`Authorization: Bearer`、`?key=`、HttpOnly Cookie 会话三种都行；
支持多 key 并存（换 key 时给旧的留过渡期）。

**WebUI**：文生图 / 图像编辑双 Tab、7 个官方 2K 档位、参考图拖拽（带 `<image1>` 点击插入）、
批量队列（一行一个 prompt，两级停止）、真实步进进度条（步数来自管线回调，不是按时间猜）、
多图网格、历史记录。

## 这个版本真正花力气的地方

**1. 把"跑不动"变成"告诉你跑多大"**
`GET /v1/fit` 按**实测标定**反算：编辑模式 1.92MP 通过 / 2.17MP OOM，文生图 7 个官方
2K 档位全过。选 2:3 档位不会再撞 OOM —— 服务端按同比例自动缩到能跑，并在
`metadata.size_note` 里说明缩过。

**2. 终止与队列**
以前**没有任何办法中断正在跑的生成**（`DELETE /v1/jobs/{id}` 只对 `queued` 生效）。
现在采样回调里挂了中断检查，命中就抛异常穿过管线：实测 40 步的任务走到第 26 步按取消，
**0.8 秒内**结束并返回 **499**（不是 500 —— 调用方要能区分"我取消了"和"真出错"）。

**3. 生成图自带完整元数据**
PNG 的 iTXt 块（键 `qwen_image_21`）里写进：prompt / 负向词 / 步数 / **实际种子** /
模型**全量 SHA-256**（29 文件 33 GB 一次算完并缓存）/ 每张参考图的 sha256 / 耗时分段 /
torch·CUDA·GPU 版本。载荷带 `schema_version`，**加字段不破坏老读取方**。
`python tools/read_metadata.py 图.png --verify` 可校验内容指纹。

**4. 自动落盘**
`outputs/YYYY-MM-DD/序号-seed.png`，落盘那份与 API 返回的那份**逐字节一致**。

## 上手

```bash
git clone https://github.com/chibimiku/qwen-image-2.1-tools
cd qwen-image-2.1-tools

# 1) 传服务端（本机执行，约 3 秒；凭据存进 git-ignored 的 tools/autodl.env）
python tools/deploy_service.py --host <实例域名> --port <端口> --password <密码> --save-env

# 2) 装依赖 + 下权重（约 20~40 分钟）+ 起服务
ssh -p <端口> root@<实例域名> 'bash /root/qwen-image-2.1/scripts/bootstrap.sh'

# 3) 对账：逐文件 md5 比对"实例上跑的"与"仓库提交的"
python tools/check_deploy.py
```

需要 **≥40 GB 显存**的单卡（实测 RTX 4090 48G 全 BF16 常驻）。详细映射与坑见
[docs/DEPLOY.md](docs/DEPLOY.md)。

## ⚠️ 许可证：代码 MIT，模型**不是**

- 本仓库代码：**MIT**。
- Qwen-Image-2.1 模型权重：**Qwen Research License**，
  `"Non-Commercial" shall mean for research or evaluation purposes only`，
  商用需另行授权。原文存放在 [docs/upstream/qwen-image-2.1-LICENSE.txt](docs/upstream/qwen-image-2.1-LICENSE.txt)。

**别把本仓库的 MIT 当成可以对模型随便商用。**

## 文档（按"你想解决什么"排）

| 想做的事 | 看 |
|---|---|
| 部署到新机器 | [docs/DEPLOY.md](docs/DEPLOY.md) |
| 调接口 | [docs/API.md](docs/API.md) |
| 选分辨率 / 搞懂 `output_resolution` | [docs/RESOLUTION.md](docs/RESOLUTION.md) |
| **人体崩坏（多条腿）怎么优化** | [docs/PROMPT-ANATOMY.md](docs/PROMPT-ANATOMY.md) |
| 读生成图里的元数据 | [docs/METADATA.md](docs/METADATA.md) |
| 看全部实测数据 | [docs/MEASUREMENTS.md](docs/MEASUREMENTS.md) |
| 看每轮改了什么、修了什么 | [docs/CHANGELOG.md](docs/CHANGELOG.md) |

`docs/upstream/` 里放了**官方文档与源码的本地副本**（含两个 prompt-rewriter 的
system prompt 原文），文档里的每条断言都标了出处行号，并可用
`python tools/check_doc_refs.py` 自查引用是否失效。

## 已知限制（不粉饰）

- **人体崩坏是概率问题**：prompt 优化能降低概率，不能消除。仓库里的 `anatomy_check`
  复检器**判据保守**（实测连"腿绞成一团"都判 PASS），当兜底可以，**别当质量保证**。
- **面部一致性靠链路外补偿**：这个模型每次编辑都会重绘整张图（含脸），
  prompt 里写"保持面部"锁不住；`service/face_fix.py` 把源图脸贴回是唯一有效手段。
- **`negative_prompt` + CFG 的有效性尚未定论**：官方只说过该模型按无引导设计
  （`true_cfg_scale=1.0`），**没有给过负面词表**。UI 里那两个负面词按钮是**项目自编**，
  已明确标注。实验方案见 [docs/CFG-NEGATIVE-AB-TEST.md](docs/CFG-NEGATIVE-AB-TEST.md)，
  阈值与评分方法都写好了，**等有人按它跑完再下结论**。
- **`test-data/` / `reports/` / `outputs/` 未入库**（约 300 MB 实验产物），
  需要图就照 `docs/MEASUREMENTS.md` 里的命令重跑。
- **单卡串行**：同一时刻只跑一个生成，靠 `_gpu_lock` 排队。

## 仓库里都有什么

```
service/    部署载荷（结构与实例 /root/qwen-image-2.1/ 一一对应）
  server.py     HTTP 服务 · ui/ 控制台 · anatomy_check.py 人体复检 · face_fix.py 人脸回贴
  scripts/      serve.sh 启停 · bootstrap.sh 一键恢复 · qwen_env.sh 环境变量 · 模型下载
docs/       全部文档 + 官方材料本地副本（upstream/，带出处行号）
tools/      本机工具：部署/对账/元数据读取/产物拉取/提交前凭据扫描/5 个自检脚本
remote/     remote/scripts/ 实例上跑的一次性脚本（探测与实验）
```

## 校验过的东西

出图前先跑这几个（都不用 GPU）：

```bash
node tools/check_ui_js.js service/ui/index.html          # UI 内联 JS 语法 + 死递归检测
node tools/webui_check_invariants.js                      # 21 项：401/轮询/尺寸优先级等踩过的坑
python tools/check_server_size.py                         # 服务端语法 + 尺寸公式 9 例
python tools/check_doc_refs.py docs/RESOLUTION.md docs/PROMPT-ANATOMY.md   # 文档引用行号
python tools/scan_secrets.py                              # 提交前凭据扫描
```

---

**首次发布**：仓库定位是"一台机器跑起来 + 把踩过的坑写下来"。
后续方向见 `docs/CHANGELOG.md` 顶部与 `docs/CFG-NEGATIVE-AB-TEST.md`。
