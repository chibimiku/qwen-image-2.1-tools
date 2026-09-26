export PATH=/root/miniconda3/bin:$PATH
echo '=== install tail ==='
tail -12 /root/qwen-image-2.1/logs/install.log
echo '=== done? ==='
grep -c INSTALL_DONE /root/qwen-image-2.1/logs/install.log || true
pgrep -af "pip install" | grep -v pgrep | head -3
