export PATH=/root/miniconda3/bin:$PATH
chmod +x /root/qwen-image-2.1/scripts/*.sh
pkill -f watch_download.sh 2>/dev/null
nohup bash /root/qwen-image-2.1/scripts/watch_download.sh > /root/qwen-image-2.1/logs/monitor.log 2>&1 &
echo "monitor pid=$!"
sleep 3
tail -3 /root/qwen-image-2.1/logs/monitor.log
