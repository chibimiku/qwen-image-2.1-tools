#!/bin/bash
# Start / stop the Qwen-Image-2.1 HTTP service.
#   bash /root/qwen-image-2.1/scripts/serve.sh start|stop|status|fg
set -u
source /root/qwen-image-2.1/qwen_env.sh
SVC=/root/qwen-image-2.1/service/server.py
LOG=/root/qwen-image-2.1/logs/service.log
PIDF=/root/qwen-image-2.1/service.pid
CMD=${1:-status}

# 47.4G 卡上跑 2K：VAE 解码是显存尖峰，分块解码 + 可扩展段分配器都能救命
export PYTORCH_CUDA_ALLOC_CONF=${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}

case "$CMD" in
  start)
    if [ -f "$PIDF" ] && kill -0 "$(cat $PIDF)" 2>/dev/null; then
      echo "already running pid=$(cat $PIDF)"; exit 0
    fi
    cd /root/qwen-image-2.1
    nohup python "$SVC" >> "$LOG" 2>&1 &
    echo $! > "$PIDF"
    echo "started pid=$(cat $PIDF) log=$LOG offload=${QWEN_OFFLOAD:-none} tile_vae=${QWEN_TILE_VAE:-0}"
    ;;
  restart)
    bash "$0" stop; sleep 3; bash "$0" start
    ;;
  fg)
    cd /root/qwen-image-2.1
    exec python "$SVC"
    ;;
  stop)
    if [ -f "$PIDF" ]; then kill "$(cat $PIDF)" 2>/dev/null; rm -f "$PIDF"; echo stopped; else echo "no pidfile"; fi
    pkill -f 'service/server.py' 2>/dev/null || true
    ;;
  status)
    if [ -f "$PIDF" ] && kill -0 "$(cat $PIDF)" 2>/dev/null; then echo "running pid=$(cat $PIDF)"; else echo "not running"; fi
    echo "--- last log ---"; tail -8 "$LOG" 2>/dev/null
    echo "--- health ---"; curl -s -m 5 "http://127.0.0.1:${QWEN_PORT:-6006}/health" || true; echo
    ;;
  *)
    echo "usage: $0 start|stop|restart|status|fg"; exit 2;;
esac
