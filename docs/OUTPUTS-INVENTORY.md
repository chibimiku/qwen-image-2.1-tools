# 生成产物清单（只读盘点，不代表已删除）

> 生成时间：2026-09-26 20:26　生成器：`python tools/inventory_outputs.py --write`
>
> 本地 160 个文件 / 316.1 MB；远端 31 个文件 / 31.2 MB。**这些都不在 git 里**（`test-data/` `reports/` `tmp_refs/` 已 gitignore）。

## 一、本地产物

### `test-data/` — 149 个文件，298.2 MB

> 全部测试产物：输入图、每轮输出、量化 JSON、接触表

| 子目录 | 文件数 | 大小 |
|---|---|---|
| `test-data/anchor/` | 10 | 22.7 MB |
| `test-data/case_shell/` | 13 | 24.7 MB |
| `test-data/chain/` | 14 | 28.4 MB |
| `test-data/expr/` | 9 | 23.1 MB |
| `test-data/fix/` | 44 | 91.4 MB |
| `test-data/fix_check/` | 3 | 1.7 MB |
| `test-data/imageN_check/` | 8 | 2.2 MB |
| `test-data/matrix/` | 22 | 42.3 MB |
| `test-data/remote_inputs/` | 0 | 0 B |
| `test-data/remote_outputs/` | 7 | 16.3 MB |

顶层散落文件 19 个：

- `test-data/t2i_landscape_2048.png` — 5.6 MB
- `test-data/input_edit.jpg` — 3.6 MB
- `test-data/report_v2.png` — 3.6 MB
- `test-data/nsfw_L4_low_angle.png` — 2.3 MB
- `test-data/poseA_thighs_open_22.png` — 2.3 MB
- `test-data/nsfw_L2_skirt_spread.png` — 2.3 MB
- `test-data/nsfw_L3_kneeling_lean.png` — 2.3 MB
- `test-data/nsfw_L1_open_pose.png` — 2.2 MB
- `test-data/poseB_crouch_symmetric_22.png` — 2.2 MB
- `test-data/poseA_thighs_open_33.png` — 2.2 MB
- `test-data/poseB_crouch_symmetric_33.png` — 2.2 MB
- `test-data/poseA_thighs_open_11.png` — 2.2 MB
- `test-data/poseB_crouch_symmetric_11.png` — 2.2 MB
- `test-data/edit_crouching.png` — 2.2 MB
- `test-data/edit_crouching_2k.png` — 2.2 MB
- `test-data/t2i_fishing_1024.png` — 2.0 MB
- `test-data/report_top.png` — 1.5 MB
- `test-data/bench_1024_20steps.png` — 1.5 MB
- `test-data/expr_strip.png` — 901.0 KB

### `reports/` — 5 个文件，11.3 MB

> 生成的 HTML 报告（单文件、图片内嵌，可直接外发）

顶层散落文件 5 个：

- `reports/face-fix-report.html` — 10.3 MB
- `reports/matrix-report.html` — 763.9 KB
- `reports/webui-tunnel.png` — 70.6 KB
- `reports/webui-public.png` — 70.3 KB
- `reports/webui-preview.png` — 61.4 KB

### `tmp_refs/` — 6 个文件，6.6 MB

> 参考图引用语法实验的中间图（P1~P5）

顶层散落文件 6 个：

- `tmp_refs/01_plain.png` — 1.3 MB
- `tmp_refs/04_natural.png` — 1.2 MB
- `tmp_refs/05_chinese.png` — 1.2 MB
- `tmp_refs/03_angle.png` — 1.2 MB
- `tmp_refs/02_image12.png` — 1.1 MB
- `tmp_refs/compare.png` — 691.7 KB

## 二、实例上的产物

| 路径（相对根） | 文件数 | 大小 |
|---|---|---|
| `outputs` | 12 | 22.2 MB |
| `autodl-tmp/imageN_check` | 10 | 5.0 MB |
| `autodl-tmp/fix_check` | 4 | 1.5 MB |
| `autodl-tmp/follow_check` | 1 | 1.0 MB |
| `autodl-tmp/stall_check` | 2 | 1.4 MB |
| `service/ui` | 2 | 83.7 KB |

## 三、被文档引用的文件（删掉会导致 docs 断链）

- `reports/matrix-report.html`（存在 — 763.9 KB）
- `reports/webui-preview.png`（存在 — 61.4 KB）
- `reports/webui-public.png`（存在 — 70.3 KB）
- `reports/webui-tunnel.png`（存在 — 70.6 KB）
- `test-data/expr_strip.png`（存在 — 901.0 KB）
- `test-data/imageN_check/P1_none.png`（存在 — 381.1 KB）
- `test-data/remote_outputs/hug_two_people.png`（存在 — 2.4 MB）
- `test-data/report.html`（**已不存在**）

## 四、要清理的话，对应的命令

```bash
# 本地（注意：这份清单里被引用的文件会一起没掉，文档需同步改）
Remove-Item -Recurse -Force test-data, reports, tmp_refs

# 远端实例：清掉实验输出（不动权重 /root/autodl-tmp/Qwen-Image-2.1）
python tools/autodl_run.py "rm -rf /root/qwen-image-2.1/outputs/* /root/autodl-tmp/imageN_check /root/autodl-tmp/fix_check /root/autodl-tmp/follow_check /root/autodl-tmp/stall_check"
```
