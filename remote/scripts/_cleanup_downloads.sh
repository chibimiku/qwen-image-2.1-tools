#!/bin/bash
# 清理：① 我那次失败的 HF 下载残留（全是 .incomplete）② 已换掉、用不到的 SmolVLM-500M
#       ③ 下载用的临时脚本与 /tmp 中间文件
# 只删点名的路径 + HF 缓存里的半截文件，不碰 outputs/ inputs/ 里的测试图。
set -u
export PATH=/root/miniconda3/bin:$PATH
export HF_HOME=/root/autodl-tmp/hf
HUB=$HF_HOME/hub
R=/root/qwen-image-2.1

before=$(df --output=avail -B1 /root/autodl-tmp | tail -1)

echo "=== 0. 先确认服务现在用的是别的模型（不是在用 500M）==="
curl -s -m 8 localhost:6006/health | python -c "
import sys, json
d = json.load(sys.stdin)
print('  loaded=%s' % d['loaded'])
print('  anatomy_checker =', json.dumps(d.get('anatomy_checker'), ensure_ascii=False))
"

echo
echo "=== 1. 要删的东西（先列大小）==="
for p in "$HUB/models--HuggingFaceTB--SmolVLM2-2.2B-Instruct" \
         "$HUB/models--HuggingFaceTB--SmolVLM-500M-Instruct" \
         /root/_dl_smolvlm2.sh /root/_dl_watch_2b.sh /root/_dl_ms_2b.sh; do
  if [ -e "$p" ]; then printf "  %8s  %s\n" "$(du -sh "$p" 2>/dev/null | cut -f1)" "$p"; else echo "  （已不在） $p"; fi
done
echo "  --- HF 缓存里其余半截文件 ---"
find "$HF_HOME" -name '*.incomplete' -o -name '*.part' -o -name '*.tmp' 2>/dev/null \
  | while read -r f; do printf "  %8s  %s\n" "$(du -h "$f" | cut -f1)" "$f"; done

echo
echo "=== 2. 开删 ==="
rm -rfv "$HUB/models--HuggingFaceTB--SmolVLM2-2.2B-Instruct" 2>&1 | tail -2
rm -rfv "$HUB/models--HuggingFaceTB--SmolVLM-500M-Instruct" 2>&1 | tail -2
rm -fv /root/_dl_smolvlm2.sh /root/_dl_watch_2b.sh /root/_dl_ms_2b.sh 2>&1
rm -rvf /tmp/_smol_files.json /tmp/_ms_files.json /tmp/_ui_public.html /tmp/_ui_now.html 2>&1
rm -rf /tmp/_retry_cmd_*.sh /tmp/_autodl_cmd_*.sh 2>/dev/null
find "$HF_HOME" \( -name '*.incomplete' -o -name '*.part' -o -name '*.tmp' \) -delete 2>/dev/null
# 空锁目录（hf 下载留下的，删掉不影响已有快照）
find "$HUB/.locks" -type f -size 0 -delete 2>/dev/null
echo "  完成"

echo
echo "=== 3. 删完的样子 ==="
du -sh "$HF_HOME" 2>/dev/null
ls -la "$HUB" | tail -6
echo "  --- 现在 HF 缓存里还剩哪些模型 ---"
du -sh "$HUB"/* 2>/dev/null
echo "  --- 还有没有半截文件 ---"
find "$HF_HOME" \( -name '*.incomplete' -o -name '*.part' -o -name '*.tmp' \) 2>/dev/null | head

echo
echo "=== 4. 复检模型本身没被动（本地目录）==="
du -sh /root/autodl-tmp/models/SmolVLM2-2.2B-Instruct 2>&1

echo
echo "=== 5. 服务健康 + 真跑一次带复检的出图（确认功能没被清理搞坏）==="
echo "（如果服务本来就没在跑，只做文件层面的核对，不擅自替用户启动服务）"
H=$(curl -s -m 6 localhost:6006/health)
if echo "$H" | grep -q '"status"'; then
  echo "$H" | python -c "
import sys, json
d = json.load(sys.stdin)
print('  loaded=%s queue=%s' % (d['loaded'], d['queue_depth']))
print('  anatomy_checker =', json.dumps(d.get('anatomy_checker'), ensure_ascii=False))
"
  cd $R && python tools/anatomy_e2e.py --base http://127.0.0.1:6006 --key "${QWEN_TEST_KEY:-1730}" \
    --width 768 --height 1024 --steps 8 --retries 1 2>&1 \
    | grep -E "HTTP|elapsed_s\"|label|fail_open|reason|total_s" | head -10
else
  echo "  服务没在跑（实例刚开机时会这样），跳过接口验证"
  echo "  文件层面核对：复检模型目录"
  ls -la /root/autodl-tmp/models/SmolVLM2-2.2B-Instruct | head -5
fi

echo
echo "=== 6. 磁盘回收 ==="
after=$(df --output=avail -B1 /root/autodl-tmp | tail -1)
df -h /root/autodl-tmp | tail -1
python - "$before" "$after" <<'PY'
import sys
b, a = int(sys.argv[1]), int(sys.argv[2])
print("  释放: %.2f GiB（可用 %.2f → %.2f GiB）" % ((a - b) / 2**30, b / 2**30, a / 2**30))
PY
