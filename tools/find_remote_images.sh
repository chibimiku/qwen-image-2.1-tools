#!/bin/bash
# 在实例上找图片文件：覆盖业务目录，排除权重与依赖。
#
# 用法（在实例上跑，或经 tools/ssh_retry.py 调用）：
#   bash find_remote_images.sh                   # 全部业务图片
#   DAYS=7 bash find_remote_images.sh            # 只看最近 7 天改动的
#
# 为什么不用 locate：plocate 的数据库默认不索引 autodl-tmp，而且需要先 updatedb。
# 一次性排查用 find 更可靠；locate 适合反复查同一个盘。
set -u
DAYS="${DAYS:-0}"
ROOTS="${ROOTS:-/root /autodl-tmp /autodl-fs/data}"
MTIME=""
[ "$DAYS" -gt 0 ] && MTIME="-mtime -$DAYS"

echo "=== 业务目录下的图片（排除 Qwen-Image-2.1 权重 / miniconda3 / lora 素材）==="
find $ROOTS -type f \
  \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.webp' \) $MTIME \
  -not -path '*/Qwen-Image-2.1/*' \
  -not -path '*/miniconda3/*' \
  -not -path '*/site-packages/*' \
  -not -path '*/.cache/*' \
  -not -path '*/lora/*' \
  2>/dev/null | sort | while read -r f; do
    printf '%s  %8s  %s\n' "$(date -r "$f" '+%m-%d %H:%M')" "$(du -h "$f" | cut -f1)" "$f"
  done

echo
echo "=== 各目录占用 ==="
for d in /root/qwen-image-2.1/outputs /root/autodl-tmp/imageN_check \
         /root/autodl-tmp/fix_check /root/autodl-tmp/follow_check \
         /root/autodl-tmp/stall_check /root/autodl-tmp/meta_check \
         /autodl-fs/data/lora/flux /autodl-fs/data/lora/sdxl; do
  [ -d "$d" ] && printf '  %-38s %s\n' "$d" "$(du -sh "$d" 2>/dev/null | cut -f1)"
done

echo
echo "=== 素材库里的文件类型（确认那些不是产出）==="
for d in /autodl-fs/data/lora/flux /autodl-fs/data/lora/sdxl; do
  [ -d "$d" ] || continue
  echo "  $d:"
  ls "$d" 2>/dev/null | sed 's/.*\.//' | sort | uniq -c | sort -rn | head -6 | sed 's/^/    /'
done
