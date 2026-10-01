#!/bin/bash
# Qwen-Image-2.1 服务开机自启。
#
# 放在 **/root/autodl-tmp** 下是有意的：这个路径挂在持久盘 /dev/md0 上，
# 跨容器重建保留；而 /etc、/root 在 overlay 上层，实例重开就没了
# （实测：09-27 装好的服务，10-01 容器重建后 /etc 与 /init 的时间戳全部刷新）。
#
# 调用链：容器启动 → /init/bin/customer.cmd.sh（AutoDL 提供，每次重建都还原）
#         → 本脚本。所以 /init 侧只需要一行引导，丢了也能重新贴。
#
# 用法：
#   bash /root/autodl-tmp/autostart/qwen-autostart.sh            # 正常自启（幂等）
#   bash /root/autodl-tmp/autostart/qwen-autostart.sh --status   # 只查状态
#   bash /root/autodl-tmp/autostart/qwen-autostart.sh --install  # (重)装 /init 引导
#
# 设计要点：
#   · **只负责起，不负责杀**：已经活着就退出，绝不重复拉起或抢占正在跑的实例。
#   · **等 GPU 就绪**：无卡模式下 torch.cuda.is_available() 为 False，服务会退化成
#     mock 模式（只验接口契约，不出图）。所以先轮询 nvidia-smi，等不到就跳过，
#     把判断留给下一次触发，避免用一个 mock 进程占住端口。
#   · **完全后台、不阻塞启动流程**：AutoDL 的 boot.sh 会顺序执行钩子，
#     在这里前台等权重加载会把启动卡住十几分钟。
#   · **幂等**：重复执行安全（按 pidfile + 端口双重判断）。

set -u

ROOT=/root/qwen-image-2.1
LOG_DIR=$ROOT/logs
BOOT_LOG=/root/autodl-tmp/autostart/boot.log
PIDF=$ROOT/service.pid
PORT=6006
GPU_WAIT_SEC=${QWEN_AUTOSTART_GPU_WAIT:-600}   # 最多等 GPU 10 分钟
STARTUP_GRACE=${QWEN_AUTOSTART_GRACE:-180}     # 已有一个"正在起"的实例时，等它就绪的最大秒数
POLL=5

mkdir -p "$LOG_DIR" "$(dirname "$BOOT_LOG")"

log() { echo "[$(date '+%F %T')] $*" >> "$BOOT_LOG"; }

# ── 服务是否真的在处理请求 ──────────────────────────────────────────────
#
# 判据用**HTTP 探测**，不用 pidfile，也不用 /dev/tcp：
#   · 只看 pidfile 会被**陈旧 pid 文件**骗到 —— 实测遇到过一次：服务 OOM 挂了，
#     pidfile 还留着，serve.sh 认为"already running"直接退出，自启就此失效。
#   · /dev/tcp 的退出码从函数里传不出去（子 shell 里 exec 的返回码拿不到），
#     实测那次 `running` 恒为假，于是又拉起第二个实例（GPU 只有 48G，会 OOM）。
# 服务真在跑的话 /health 一定回答 200，这比任何本地状态都可靠。
alive() {
    curl -s --max-time 5 "http://127.0.0.1:$PORT/health" 2>/dev/null \
        | grep -q '"status":"ok"'
}

running() {
    alive
}

status() {
    if running; then
        local pid=""
        [ -f "$PIDF" ] && pid=$(cat "$PIDF" 2>/dev/null)
        echo "running pid=${pid:-?}"
        curl -s --max-time 5 "http://127.0.0.1:$PORT/health" 2>/dev/null | head -c 200
        echo
    else
        echo "stopped"
    fi
}

if [ "${1:-}" = "--status" ]; then
    status
    exit 0
fi

# ── --install：把引导行贴回 /init/bin/customer.cmd.sh（容器重建后需要重贴）──
if [ "${1:-}" = "--install" ]; then
    TARGET=/init/bin/customer.cmd.sh
    MARK="qwen-autostart"
    LINE="bash /root/autodl-tmp/autostart/qwen-autostart.sh >/dev/null 2>&1   # $MARK"

    # 主链路：AutoDL 官方钩子
    if [ ! -e "$TARGET" ]; then
        echo "找不到 $TARGET（不是 AutoDL 容器？）" >&2
    elif grep -q "$MARK" "$TARGET" 2>/dev/null; then
        echo "已存在，跳过：$TARGET"
    else
        cp -a "$TARGET" "$TARGET.bak.$(date +%s)"
        printf '\n# --- %s ---\n%s\n' "$MARK" "$LINE" >> "$TARGET"
        echo "已追加引导：$TARGET"
    fi

    # 退路：登录 shell 触发。**必须插在 .bashrc 的提前 return 之前** ——
    # 本机 .bashrc 第 6 行是 `[ -z "$PS1" ] && return`，非交互 shell 会在那里直接返回，
    # 追加到文件末尾的那行永远执行不到（实测踩过：退路完全没生效）。
    BR=/root/.bashrc
    if [ -f "$BR" ]; then
        if grep -q "$MARK" "$BR" 2>/dev/null; then
            # 已经贴过，但要确认它不在提前 return 之后
            first=$(grep -n "$MARK" "$BR" | head -1 | cut -d: -f1)
            guard=$(grep -n 'PS1' "$BR" | head -1 | cut -d: -f1)
            if [ -n "$first" ] && [ -n "$guard" ] && [ "$first" -gt "$guard" ]; then
                echo "退路位置不对（在第 ${first} 行，提前 return 在第 ${guard} 行）—— 重贴到前面"
                grep -v "$MARK" "$BR" | grep -v '^bash /root/autodl-tmp/autostart' > "$BR.tmp" \
                    && mv "$BR.tmp" "$BR"
                first=""
            fi
        fi
        if ! grep -q "$MARK" "$BR" 2>/dev/null; then
            cp -a "$BR" "$BR.bak.$(date +%s)"
            tmp=$(mktemp)
            {
                printf '# --- %s（退路：任何 shell 都触发一次，脚本内部幂等）---\n' "$MARK"
                printf '%s\n' "$LINE"
                printf '# --- end %s ---\n\n' "$MARK"
                cat "$BR"
            } > "$tmp" && mv "$tmp" "$BR"
            echo "已把退路插到 $BR 开头（在 '[ -z \$PS1 ] && return' 之前）"
        else
            echo "退路已存在且位置正确：$BR"
        fi
    fi

    # 顺手清掉可能存在的陈旧 pidfile：它会让 serve.sh 误判"已在运行"而拒绝自启
    if [ -f "$PIDF" ] && ! kill -0 "$(cat "$PIDF" 2>/dev/null)" 2>/dev/null; then
        echo "发现陈旧 pidfile（pid $(cat "$PIDF") 已不存在），删除"
        rm -f "$PIDF"
    fi
    exit 0
fi

# ── 主流程 ────────────────────────────────────────────────────────────────
#
# 判断链（顺序不能换）：
#   1. /health 是 ok 的        → 有人在正常服务，直接退出，绝不抢
#   2. pidfile 里的进程还在    → 大概率正在加载权重（要十几秒），
#                                给它 STARTUP_GRACE 秒；就绪了就退出，
#                                到期仍不就绪也不动它（宁可少起，不可起两个抢显存）
#   3. pidfile 是陈旧的        → 清掉，往下走启动
#
# 第 2 步是必须的：服务从启动到 /health 200 要十几秒，这期间 alive() 是 false。
# 少了这步，任何一次并发触发都会把**正在加载权重的实例挤掉**，pidfile 指向新进程、
# 旧进程变孤儿 —— 实测跑出过 5285→5647 的换进程，就是这么来的。
log "=== autostart 触发 (args: ${*:-none}) ==="

if running; then
    log "已有实例在跑，跳过（不抢占）"
    exit 0
fi

if [ ! -f "$ROOT/scripts/serve.sh" ]; then
    log "缺少 $ROOT/scripts/serve.sh —— 服务载荷不在这台机上，放弃"
    exit 0
fi

if [ -f "$PIDF" ]; then
    _pid=$(cat "$PIDF" 2>/dev/null)
    if kill -0 "$_pid" 2>/dev/null; then
        log "pidfile 指向 pid=$_pid 且进程存在 —— 给 ${STARTUP_GRACE}s 宽限期"
        _g=0
        while [ "$_g" -lt "$STARTUP_GRACE" ]; do
            if alive; then
                log "宽限期内服务已就绪（等了 ${_g}s），退出（不重复拉）"
                exit 0
            fi
            if ! kill -0 "$_pid" 2>/dev/null; then
                log "宽限期内 pid=$_pid 已退出"
                break
            fi
            sleep 5
            _g=$((_g + 5))
        done
        if kill -0 "$_pid" 2>/dev/null; then
            log "宽限期 ${STARTUP_GRACE}s 结束，pid=$_pid 仍在但 /health 未就绪"
            log "不动它（无卡模式或加载异常都交给人来判断，绝不起第二个实例抢显存）"
            exit 0
        fi
    fi
    log "清理陈旧 pidfile（pid=${_pid:-?} 已不存在）"
    rm -f "$PIDF"
fi

# 等 GPU：无卡模式起来的服务是 mock，宁可不起，等下一次触发
waited=0
while [ "$waited" -lt "$GPU_WAIT_SEC" ]; do
    if nvidia-smi -L >/dev/null 2>&1; then
        log "GPU 就绪（等了 ${waited}s）"
        break
    fi
    sleep "$POLL"
    waited=$((waited + POLL))
done
if ! nvidia-smi -L >/dev/null 2>&1; then
    log "等了 ${GPU_WAIT_SEC}s 仍无 GPU（无卡模式？）—— 跳过，避免起成 mock 实例"
    exit 0
fi

# ── 起服务：先清干净，再起 ────────────────────────────────────────────────
#
# **这一步不能省。** 实测踩到的坑：serve.sh 的 stop 是 `kill`（SIGTERM）后立刻返回，
# 但常驻 33 GB 权重的进程要**几秒到几十秒**才真正退出并释放显存。如果此时直接起新的，
# 会出现：新进程 bind 6006 失败（address already in use）+ 加载权重 OOM
# （旧的还占着 28 GiB）。日志里就是这么写的，最后留下一个"活着但 loaded=false"的僵尸服务，
# pidfile 还指向一个早就死掉的 pid。
#
# 所以：动手起之前，先确保服务器上没有别的 server.py 在跑、显存也放干净了。
KILL_WAIT=${QWEN_AUTOSTART_KILL_WAIT:-60}      # 等旧进程退出并释放显存的最大秒数

houseclean() {
    local victims
    victims=$(pgrep -f 'service/server\.py' 2>/dev/null || true)
    [ -z "$victims" ] && return 0

    log "发现残留的 server.py 进程（$(echo "$victims" | tr '\n' ' ')）—— 先清理再启动"
    # shellcheck disable=SC2086
    kill $victims 2>/dev/null || true
    local w=0
    while [ "$w" -lt "$KILL_WAIT" ]; do
        if ! pgrep -f 'service/server\.py' >/dev/null 2>&1; then
            log "残留进程已退出（等了 ${w}s）"
            break
        fi
        sleep 2
        w=$((w + 2))
    done
    if pgrep -f 'service/server\.py' >/dev/null 2>&1; then
        log "等了 ${KILL_WAIT}s 仍有残留，SIGKILL"
        # shellcheck disable=SC2046
        kill -9 $(pgrep -f 'service/server\.py' 2>/dev/null) 2>/dev/null || true
        sleep 3
    fi

    # 等显存真的放掉：进程没了但显存没释放的情况是有的（驱动回收有延迟）
    local g=0
    while [ "$g" -lt "$KILL_WAIT" ]; do
        local free_mib
        free_mib=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1)
        if [ -n "$free_mib" ] && [ "$free_mib" -ge 30000 ] 2>/dev/null; then
            log "显存已释放（free ${free_mib}MiB，等了 ${g}s）"
            break
        fi
        sleep 2
        g=$((g + 2))
    done
    rm -f "$PIDF" 2>/dev/null
    return 0
}

houseclean

log "启动服务：bash $ROOT/scripts/serve.sh start"
if bash "$ROOT/scripts/serve.sh" start >> "$BOOT_LOG" 2>&1; then
    log "serve.sh start 返回 0"
else
    log "serve.sh start 返回非 0（详见上面的输出）"
fi

# 记一笔就绪时间，方便事后核对（不阻塞启动流程）
(
    for _ in $(seq 1 90); do
        sleep 10
        if curl -s --max-time 5 "http://127.0.0.1:$PORT/health" 2>/dev/null | grep -q '"status":"ok"'; then
            log "health ok（启动后约 $((_ * 10))s）"
            exit 0
        fi
    done
    log "等了 900s 仍未 /health 200 —— 去看 $LOG_DIR/service.log"
) >/dev/null 2>&1 &

log "已发起启动，退出（不阻塞 boot）"
exit 0
