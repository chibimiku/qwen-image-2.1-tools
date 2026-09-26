export PATH=/root/miniconda3/bin:$PATH
echo '=== 线上页面是否已含问号提示 ==='
curl -s localhost:6006/ > /tmp/ui_now.html
python3 - <<'PY'
h = open('/tmp/ui_now.html', encoding='utf-8').read()
checks = [
    ('页面字节数', len(h), ''),
    ('问号元素 class="q"', h.count('class="q"'), ''),
    ('tip 内容块', h.count('class="tip"'), ''),
    ('提到 multi-subject', 'multi-subject' in h, ''),
    ('提到 image[-1] 说明', 'image[-1]' in h, ''),
    ('引用官方 README', '官方 README' in h, ''),
    ('含拥抱示例说明', '拥抱' in h, ''),
    ('含 1.92MP 上限提示', '1.92MP' in h, ''),
    ('含 64 通道 RGBA 说明', '64 通道' in h, ''),
    ('含 7 个官方 2K 档位', '2752×1536' in h, ''),
]
for name, val, _ in checks:
    print(f"  {name:26s} {val}")
PY

echo
echo '=== 文件到位确认 ==='
ls -la /root/qwen-image-2.1/service/ui/ /root/qwen-image-2.1/*.md 2>/dev/null | head -12
