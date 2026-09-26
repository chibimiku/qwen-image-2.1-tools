export PATH=/root/miniconda3/bin:$PATH
echo '=== 输出目录清单 ==='
for d in /root/qwen-image-2.1/outputs /root/qwen-image-2.1/outputs/*; do
  [ -e "$d" ] && echo "--- $d" && ls -la "$d" 2>/dev/null | head -40
done
echo
echo '=== 全盘找生成的图片 ==='
find /root -type f \( -name '*.png' -o -name '*.jpg' -o -name '*.jpeg' -o -name '*.webp' \) \
     -newermt '2026-09-26' 2>/dev/null | grep -v autodl-tmp | head -40
echo
echo '=== 统计 ==='
find /root/qwen-image-2.1/outputs -type f 2>/dev/null | wc -l
du -sh /root/qwen-image-2.1/outputs 2>/dev/null
echo
echo '=== 有没有子目录（比如按日期分的）==='
find /root/qwen-image-2.1/outputs -type d 2>/dev/null
