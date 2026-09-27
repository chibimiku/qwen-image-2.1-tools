# service/ui/docs/ —— 控制台要打开的官方原文

这个目录是**官方文档的副本**，跟 `service/` 一起走常规部署载荷上实例，
控制台 prompt 输入框下面那排按钮（`index.html` 的 `#docrow`）点的就是这里；
服务端在 `server.py` 的 `/v1/style-docs` 路由里按**白名单文件名**读取，
不暴露整个目录，也不接受任何用户输入拼路径。

## 为什么是"复制"而不是让部署去读仓库根的 `docs/`

`tools/deploy_service.py` 的载荷只有 `service/**` 一棵树。要让实例上的服务读到
仓库根的 `docs/upstream/`，就得给部署脚本单开一条传输规则、并且把 `deploy_manifest`
的目录映射扩到仓库根。放进 `service/ui/docs/` 则零额外机制——代价是两份文件会漂移。

漂移用检查挡住：

```powershell
python tools\deploy_style_docs.py --check-sync   # 比对两份哈希，DRIFT 会报出来
python tools\deploy_style_docs.py                # 从 docs/upstream 同步过来（本地）
```

**规则：改官方文本时先改 `docs/upstream/`，再跑一次上面的同步**，不要直接手改这里。

## 文件

| 文件 | 来源 | 说明 |
|---|---|---|
| `prompt-rewriter-T2I-system-prompt.txt` | `docs/upstream/` 同名文件 | Qwen-Image-2.1-PE-T2I 的 system prompt，八步法 |
| `prompt-rewriter-I2I-system-prompt.txt` | `docs/upstream/` 同名文件 | Qwen-Image-2.1-PE-I2I 的 system prompt，含 Attribute Disentanglement |
| `qwen-image-2.1-hf-modelcard.md` | `docs/upstream/` 同名文件 | 能力概览、官方宽高比档位、RGBA 推荐写法 |
| `qwen-image-2.1-prompt-rewriting.md` | 由 `docs/upstream/qwen-image-2.1-github-README.md` 的「Prompt Rewriting」一节节选 + 一段"与本服务的关系" | 两个 PE checkpoint、输入输出格式、接进管线的示例 |

后两者是 `.md`，服务端统一按 `text/plain` 内联返回，浏览器直接看到原文而不是渲染后的页面——
这一排按钮的目的是**照着写 prompt**，纯文本更合用。

## 它不是什么

- **不是自动改写**。本服务跑 `QwenImage21Pipeline` 原始管线，收到 prompt 直接编码。
  两个 PE 是独立的 9B VL checkpoint，要另起服务或离线跑一遍才行。
- **不是官方推荐的全部内容**。官方 README 的其余章节（安装、量化、其它框架支持）
  没放进来，需要时直接看仓库里的 `docs/upstream/`。
