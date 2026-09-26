export PATH=/root/miniconda3/bin:$PATH
echo '=== install ==='
grep -E 'Successfully installed (diffusers|fastapi|uvicorn|python-multipart)|INSTALL_DONE|ERROR|error:' /root/qwen-image-2.1/logs/install.log | tail -8
echo '=== pip procs ==='
pgrep -af "pip install" | grep -v pgrep | head -3
echo '=== download progress ==='
du -sh /root/autodl-tmp/Qwen-Image-2.1 2>/dev/null
df -h /root/autodl-tmp | tail -1
pgrep -af "snapshot_download|modelscope" | grep -v pgrep | head -3
tail -c 600 /root/qwen-image-2.1/logs/download.log | tr '\r' '\n' | tail -6
