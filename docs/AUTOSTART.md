# 开机自启：实例重启后服务自己起来

**结论先说**：AutoDL 这台机器上 **systemd 用不了**（PID 1 是 `bash /init/boot/boot.sh`），
所以自启挂在 AutoDL 官方的 `/init/bin/customer.cmd.sh` 上，脚本本体放**持久盘**
`/root/autodl-tmp/`。已验证两条链路各自可用、并发触发不重复起实例。

---

## 一、这台机的启动机制（实测）

| 事实 | 证据 |
|---|---|
| PID 1 是 bash，不是 systemd | `readlink -f /proc/1/exe` → `/usr/bin/bash`；`systemctl is-system-running` → `offline` |
| systemd 装了但没在跑 | `systemctl status` → `System has not been booted with systemd as init system` |
| 没有 `/etc/rc.local` | 不存在 |
| AutoDL 的注入点是 `/init/bin/customer.cmd.sh` | 它每次启动执行 `bash /etc/autodl.sh` |
| `/etc/autodl.sh` 一直是空的 | `/tmp/autodl.sh.log` 里留着 `bash: /etc/autodl.sh: No such file or directory` |

> **所以别照抄"写个 systemd unit"这种通用做法** —— 在这台机上它永远不会被调用。

### 持久化边界（决定脚本放哪）

```
/init                → /dev/md0（持久）  ← AutoDL 每次重建会由镜像还原
/root/autodl-tmp     → /dev/md0（持久）  ← 放这里
/                    → overlay 上层      ← 容器重建即丢
  /etc、/root、/usr 都在 overlay 上
```

实测：09-27 装好的服务，10-01 容器重建后 `/etc` 与 `/init` 的时间戳全部刷新，
但 `/root/autodl-tmp` 里的权重（33 GB）完好。

**推论**：脚本必须住 `/root/autodl-tmp`；`/init` 侧只留一行引导 —— 它是镜像还原的，
丢了用 `--install` 重贴即可。

---

## 二、调用链

```
容器启动
  └─ /init/bin/customer.cmd.sh        （AutoDL 提供，镜像每次还原）
       └─ /root/autodl-tmp/autostart/qwen-autostart.sh   （持久盘，自己维护）
            └─ /root/qwen-image-2.1/scripts/serve.sh start

退路（任何 shell 都触发一次，脚本内部幂等）
  └─ /root/.bashrc 里的一行（**带 `--quick`**，见第七节坑 5）
```

挂上之后 `customer.cmd.sh` 的尾部就是：

```bash
# --- qwen-autostart ---
bash /root/autodl-tmp/autostart/qwen-autostart.sh >/dev/null 2>&1   # qwen-autostart
```

而 `.bashrc` 头部是：

```bash
# --- qwen-autostart（退路：任何 shell 都触发一次，--quick 不阻塞登录）---
bash /root/autodl-tmp/autostart/qwen-autostart.sh --quick >/dev/null 2>&1   # qwen-autostart
# --- end qwen-autostart ---
```

两条链路的参数**故意不同**：`/init` 钩子跑在容器启动路径上，可以等（等 GPU、
等权重加载）；`.bashrc` 退路跑在**每条 ssh/sftp/scp 的会话路径**上，必须 `--quick`
立刻返回，否则每一条连接都要陪着等满宽限期（见第七节坑 5、坑 6）。

---

## 三、判断链（顺序不能换）

```
1. /health 返回 ok                → 有人在正常服务，直接退出，绝不抢
2. --quick？是 → 立刻退出         → 登录路径不等，启动交给 /init 钩子
3. pidfile 指向的进程**是我们的 server.py**（cmdline 校验）
                                  → 大概率正在加载权重（要十几秒）
                                    给它 180s 宽限期；就绪就退出；
                                    到期仍不就绪也**不动它**（宁可少起，不可起两个抢显存）
4. pidfile 陈旧 / 张冠李戴         → 清掉，往下走
5. houseclean：清残留进程 + 等显存真正释放
6. serve.sh start
```

第 3、5 步都是**踩出来的**，不是设计时想到的，见下一节。

---

## 四、跑测试才发现的四个坑

### 1. `serve.sh stop` 不等待 → 起新实例必撞车

`serve.sh` 的 stop 是 `kill`（SIGTERM）后**立刻返回**，但常驻 33 GB 权重的进程
要**几秒到几十秒**才真正退出。此时起新的，日志里就是：

```
ERROR: [Errno 98] error while attempting to bind on address ('0.0.0.0', 6006): address already in use
[startup] preload failed: OutOfMemoryError ... Process 11145 has 19.70 GiB memory in use
```

最后留下一个 "活着但 `loaded:false`" 的僵尸服务，pidfile 还指向早就死掉的 pid。

→ 加了 `houseclean()`：起之前先清掉残留的 server.py、等显存真的放掉（free ≥ 30 GB）。

### 2. 陈旧 pidfile 会静默掐死自启

服务 OOM 挂掉后 pidfile 还在，`serve.sh` 认为 "already running" 直接退出 ——
**自启就此失效，而且不报错**。

→ 起之前检查 pidfile 指向的进程是否还在，不在就清掉。

### 3. 清 pidfile 需要宽限期

服务从启动到 `/health` 200 要十几秒，这期间 `alive()` 是 false。若此时直接删 pidfile
再起一个，会把**正在加载权重的那个实例挤掉** —— 实测跑出过 pid 5285→5647 的换进程。

→ 给 180 秒宽限期；到期仍不就绪就退出，交给人工判断。

### 4. 判据不能用 pidfile，也不能用 `/dev/tcp`

- 只看 pidfile：会被陈旧文件骗到（坑 2）
- `/dev/tcp`：**函数里拿不到子 shell 的退出码**，实测 `running` 恒为假，于是又拉一个

→ 改用 **`/health` 的 HTTP 探测**。服务真在跑的话它一定回答 200，比任何本地状态可靠。

另外：**这个镜像没有 `ss`，也没有 `netstat`**，要看监听端口得读 `/proc/net/tcp`
（6006 = `0x1776`，状态 `0A` = LISTEN）。

### 5. 只看 `kill -0 pid` → 平台进程冒充服务，自启静默失效（10-07 事故）

现象：平台入口一路 404，`/health` 连不上，但 autostart 每 3 分钟准时报到一次
"给宽限期"、"不动它"，从不拉起服务。

```
[19:01:09] pidfile 指向 pid=944 且进程存在 —— 给 180s 宽限期
[19:04:09] 宽限期 180s 结束，pid=944 仍在但 /health 未就绪
[19:04:09] 不动它（无卡模式或加载异常都交给人来判断，绝不起第二个实例抢显存）
```

根因：pidfile 里写着 `944`，而 944 **不是** webui —— 它是 AutoDL 自己的
`autopanel serve`：

```
$ tr '\0' ' ' < /proc/944/cmdline
autopanel serve --work-dir=/root/autodl-tmp --cache-dir=/root/autodl-tmp
$ ls -l /proc/944/fd
6 -> /root/autodl-tmp/.autodl/autopanel.monitor.db
```

`kill -0 944` 当然成功（那是个活得好好的平台进程），于是脚本每次都认定"服务正在起"，
让路 180 秒后退出，真正的 `server.py` **一次都没被拉起来过**。pid 号是会被复用的，
"这个 pid 活着"和"我们的服务活着"是两件事。

→ 认进程看 `cmdline`（`is_webui_pid()`，直接读 `/proc/<pid>/cmdline`，不依赖
`pgrep`——这个镜像里连 `ss` 都没有，别赌别的工具在）。pid 活着但不是 `server.py`
就按陈旧 pidfile 处理：清理、往下走、把服务起起来。

### 6. 把全量自启挂在 `.bashrc` 上 → 每条 ssh 都要等满宽限期

现象：任何一次 ssh/sftp/cp 连接，**命令与回显之间固定卡 181 秒**，且过期会话
一次性吐全部输出，看起来像"远端极慢"或"网络抖动"。`boot.log` 里能对上时间：

```
[19:13:26] === autostart 触发 (args: none) ===     ← 我这条 ssh 建会话的时刻
[19:13:26] pidfile 指向 pid=944 且进程存在 —— 给 180s 宽限期
[19:14:11] 宽限期 180s 结束
```

`.bashrc` 的退路是**登录 shell 路径**，会同步执行整个判断链；只要 pidfile 那步要等，
每条连接就陪着等。而 ssh 一把把开新会话（自动化脚本、sftp、scp 都是），代价成倍放大。

→ 退路一律带 `--quick`：`/health` ok 就退出，不 ok 也立刻返回，启动只交给
`/init` 钩子。修完实测：会话建立 + 执行整条部署 **5.6 秒**（原先光等就是 181 秒）。

---

## 五、日常用法

```bash
# 看状态（自启脚本视角）
bash /root/autodl-tmp/autostart/qwen-autostart.sh --status

# 只探一下（登录路径用的就是它，绝不等待）
bash /root/autodl-tmp/autostart/qwen-autostart.sh --quick

# 重贴引导（容器重建、或换了新容器之后）
bash /root/autodl-tmp/autostart/qwen-autostart.sh --install

# 看自启记录
tail -20 /root/autodl-tmp/autostart/boot.log
```

从本机（仓库里）：

```bash
python tools/deploy_autostart.py          # 上传 + 语法检查 + 装引导 + 状态
python tools/deploy_autostart.py --check  # 只看状态
python tools/deploy_autostart.py --dry-run # 只上传+语法检查，不装引导
python tools/deploy_autostart.py --host X --port Y   # 换目标实例
python tools/_autostart_verify.py         # **重启后**验证自启（只读；会等 SSH 回来）
python tools/_autostart_verify.py --no-wait   # 不等，立刻出结论
python tools/_remote_exec.py "<命令>" --connect-wait 600   # 在实例上跑命令（可等重启）
python tools/_autostart_e2e.py            # 端到端验证（会停一次服务，约 3 分钟）
python tools/_svc_procs.py                # 精确看进程与显存占用
python tools/_svc_watch_load.py 240       # 盯权重加载到 loaded=true
```

**实例关机/重启之后**，第一件事跑 `tools/_autostart_verify.py`（只读，不改东西）。
它会检查四件事并直接给结论：

1. `/init/bin/customer.cmd.sh` 的引导行还在不在（**容器重建会按镜像还原 /init**，
   这行丢了就没有容器启动触发了）
2. `.bashrc` 退路是不是 `--quick` 版本
3. `boot.log` 里重启后走了哪条分支
4. 本机 `/health` 的 `status`/`loaded`，以及平台入口 8443 的 HTTP 码

> **目标实例写在 `tools/deploy_autostart.py` 的 `DEFAULT_HOST` 里，别去读 env 文件。**
> 这台机器上同时躺着两套过期配置：`tools/tunnel.conf` 指 westb:43611、
> `tools/autodl_new.env` 指 westc:17045，两个实例都早没了。按 env 部署会打到空地址。
>
> **改了脚本一定要走这个部署器，别只改远端。** 远端 `/root/autodl-tmp/autostart/`
> 是持久盘（跨容器重建保留），`git` 里的 `remote/autostart/qwen-autostart.sh` 才是真源；
> 只改远端 → 下次别人部署就回退，只改本地 → 当前实例没生效。
> 部署器还会顺带 `--install` 重贴 `/init` 钩子和 `.bashrc` 退路，这两处一漏，
> 容器一重建就又没有自启了。

### 可调的环境变量

| 变量 | 默认 | 含义 |
|---|---|---|
| `QWEN_AUTOSTART_GPU_WAIT` | 600 | 等 GPU 就绪的最大秒数（无卡模式直接跳过，避免起成 mock） |
| `QWEN_AUTOSTART_GRACE` | 180 | 已有实例在加载时，等它就绪的最大秒数 |
| `QWEN_AUTOSTART_KILL_WAIT` | 60 | 清残留进程后等显存释放的最大秒数 |

---

## 六、排障

| 现象 | 原因 | 处理 |
|---|---|---|
| 重启后服务没起来 | 引导行被容器重建冲掉了 | `--install` 重贴；看 `boot.log` 有没有触发记录 |
| **入口 404，但 boot.log 一直"给宽限期/不动它"** | **pidfile 指向平台进程（autopanel 等），不是 server.py** | **新版脚本已能识破；老版本删掉 `service.pid` 再触发一次** |
| **每条 ssh/sftp 都卡 3 分钟才回话** | **`.bashrc` 退路跑的是全量流程，在等宽限期** | **退路加 `--quick`（`--install` 会自动升级）** |
| `health` 是 ok 但不出图 | 权重没加载完，或加载失败 | **看 `loaded` 字段**，失败原因写在 `load_error` 里 |
| 日志有 `address already in use` | 旧实例还在退出中 | 跑一次自启脚本（它会 houseclean），或 `_svc_procs.py` 看谁占着 |
| 日志有 `OutOfMemoryError` | 有孤儿进程占显存 | `_svc_procs.py` 确认，`pkill -f 'service/server\.py'` 后重起 |
| 起来了但是 mock 模式 | 容器在无卡模式 | 正常行为 —— 脚本故意不占端口，等有卡再起 |

> **`/health` 在权重加载完成之前就返回 `status:"ok"`。** 判"能不能出图"必须看
> `"loaded":true`，光看 health 会误判。

---

## 七、验证记录

`tools/_autostart_e2e.py` 的 15 项断言，全部通过：

- 链路 1（`customer.cmd.sh`）：服务被拉起、是真实模式而非 mock
- 链路 2（`~/.bashrc` 退路）：在**非交互 shell** 路径下也能拉起（已确认插在第 2 行、
  `[ -z "$PS1" ] && return` 在第 10 行）
- 并发触发：加载窗口内重复触发**没有换进程**（pid 13960 → 13960）
- 幂等：就绪状态下重复触发不换进程、6006 只有一个 LISTEN、GPU 上只有一个服务进程
- 陈旧 pidfile：伪造死 pid 后能识破并正常拉起
- 收尾：`loaded:true`、无 `load_error`、真实模式、公网入口 200

### 10-07 补测（坑 5 / 坑 6 两个修复）

**会话耗时**（坑 6）：修复前每条 ssh/sftp/scp 固定拖到 ~181 秒，修复后同一套操作：

```
[会话建立 0.2s]              ← 修复前是 181.4s
python tools/deploy_autostart.py  全程 5.6s（上传+语法检查+替换+状态）
```

**进程身份校验**（坑 5）：伪造 `service.pid` 指向 autopanel 的 pid（复现事故现场），
再跑全量触发：

```
### C. pidfile 现在 = 907  cmdline: autopanel serve --work-dir=/root/autodl-tmp ...
### D. --quick        → 耗时 0s（修复前会被拖满 180s）
### E. 全量触发        → 耗时 0s
    [19:20:02] pidfile 指向 pid=907，但它不是我们的服务（cmdline: autopanel serve ...）—— 按陈旧处理
    [19:20:02] 清理陈旧 pidfile（pid=907 不是存活的 server.py）
    [19:20:02] GPU 就绪（等了 0s）→ serve.sh start → started pid=8939
### F. health OK 约 20s；pidfile 现在 = 8939，cmdline 是 python .../service/server.py
### H. loaded=true / mock=false
```

**引导落位**：`--install` 后 `grep -c qwen-autostart` →
`/init/bin/customer.cmd.sh:2`、`/root/.bashrc:3`，且 `.bashrc` 里是 `--quick` 版本。<br>
（注：首次部署时 `/init` 侧是 0 —— 钩子从来没贴过，全靠 `.bashrc` 退路在扛；
`tools/deploy_autostart.py` 现在每次都会顺手 `--install`，不会再漏。）
