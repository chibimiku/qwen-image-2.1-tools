#!/bin/bash
# 清理前先看清楚：有哪些半截下载、哪些缓存目录、谁还在引用 500M
export PATH=/root/miniconda3/bin:$PATH
export HF_HOME=/root/autodl-tmp/hf
R=/root/qwen-image-2.1

echo "=== A. HF 缓存目录一览 ==="
du -sh $HF_HOME/hub/* 2>/dev/null
echo "--- xet / 其他 ---"
du -sh $HF_HOME/xet $HF_HOME/.locks 2>/dev/null
ls -la $HF_HOME | tail -6

echo
echo "=== B. 半截下载（*.incomplete / *.part / *.tmp）==="
find $HF_HOME /root/autodl-tmp/models -name '*.incomplete' -o -name '*.part' -o -name '*.tmp' 2>/dev/null \
  | while read -r f; do printf "  %10s  %s\n" "$(stat -c %s "$f")" "$f"; done
echo "  合计: $(find $HF_HOME /root/autodl-tmp/models \( -name '*.incomplete' -o -name '*.part' -o -name '*.tmp' \) 2>/dev/null | wc -l) 个"

echo
echo "=== C. 谁还在引用 500M ==="
grep -rn "SmolVLM-500M" $R/*.sh $R/scripts/ $R/service/ 2>/dev/null | head -10
echo "--- 服务实际加载的模型 ---"
curl -s -m 8 localhost:6006/health | python -c "
import sys, json
print(' ', json.dumps(json.load(sys.stdin).get('anatomy_checker'), ensure_ascii=False))
"

echo
echo "=== D. 其他临时文件 ==="
ls -la /root/_dl_*.sh 2>/dev/null
ls -la /tmp/_smol_files.json /tmp/_ms_files.json /tmp/_ui*.html /tmp/_retry_cmd_*.sh 2>/dev/null | head
echo "--- 日志大小 ---"
du -sh $R/logs/*.log 2>/dev/null | tail -6

echo
echo "=== E. 磁盘现状 ==="
df -h /root/autodl-tmp | tail -1
