export PATH=/root/miniconda3/bin:$PATH
echo '=== download ==='
du -sh /root/autodl-tmp/Qwen-Image-2.1
find /root/autodl-tmp/Qwen-Image-2.1 -name '*.incomplete' | wc -l
find /root/autodl-tmp/Qwen-Image-2.1 -name '*.safetensors' -printf '%10s %p\n'
grep -c DOWNLOAD_DONE /root/qwen-image-2.1/logs/download2.log || true
echo '=== which python is the jupyter kernel ==='
python -c "import sys;print(sys.executable)"
ls /root/qwen-image-2.1
