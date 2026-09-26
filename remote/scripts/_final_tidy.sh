export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
echo '=== 1) 释放被缓存攥住的显存 ==='
curl -s -m 30 -X POST localhost:6006/v1/admin/empty_cache -H "Authorization: Bearer $QWEN_API_KEY" \
 | python3 -c "import sys,json;d=json.load(sys.stdin);g=d['gpu'];print(f\"  释放 {d['freed_gib']} GiB  ->  空闲 {g['free_gb']}G / 已用 {g['reserved_gb']}G\")"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader

echo
echo '=== 2) show_url.sh 新版自测 ==='
bash /root/qwen-image-2.1/scripts/show_url.sh 2>&1 | sed -n '1,30p'

echo
echo '=== 3) 磁盘 / 镜像前体检 ==='
df -h / /root/autodl-tmp | sed -n '1,4p'
echo "  /root/qwen-image-2.1 大小: $(du -sh /root/qwen-image-2.1 | cut -f1)"
echo "  pip 缓存:                 $(du -sh /root/.cache/pip 2>/dev/null | cut -f1 || echo 无)"
echo "  __pycache__ 目录数:       $(find /root/qwen-image-2.1 -name __pycache__ -type d | wc -l)"
echo "  日志目录:                 $(du -sh /root/qwen-image-2.1/logs | cut -f1)"
echo
echo '=== 4) 输出目录最终清单 ==='
ls -la /root/qwen-image-2.1/outputs/
echo "  文件数 $(find /root/qwen-image-2.1/outputs -type f | wc -l) / 总 $(du -sh /root/qwen-image-2.1/outputs | cut -f1)"
