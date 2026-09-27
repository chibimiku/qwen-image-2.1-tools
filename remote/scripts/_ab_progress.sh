#!/bin/bash
# 看实验速度与显存
set -u
echo "=== 已出图 ==="
ls /root/exp_out/*.png 2>/dev/null | wc -l
echo
echo "=== 最近 8 张的生成时刻（间隔即每张耗时）==="
ls -t --time-style='+%m-%d %H:%M:%S' -l /root/exp_out/*.png 2>/dev/null | head -9 | awk '{print "  " $6, $7, "  " $NF}'
echo
echo "=== 进程还在吗 ==="
pgrep -f _cfg_ab_generate.py >/dev/null && echo "  在跑" || echo "  已结束"
echo
echo "=== 显存 ==="
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
echo
echo "=== 日志（含被缓冲的）==="
wc -c /root/_ab_gen.log
tail -c 600 /root/_ab_gen.log
