export PATH=/root/miniconda3/bin:$PATH
df -m /root/autodl-tmp | tail -1
A=$(du -sm /root/autodl-tmp/Qwen-Image-2.1 | cut -f1)
S1=$(cat /proc/net/dev | awk '/eth0|ens/{s+=$2} END{print s}')
sleep 60
B=$(du -sm /root/autodl-tmp/Qwen-Image-2.1 | cut -f1)
S2=$(cat /proc/net/dev | awk '/eth0|ens/{s+=$2} END{print s}')
echo "delta=${B}-${A}=$((B-A))MB/min  -> $(( (B-A)/60 )) MB/s (du)"
echo "net rx = $(( (S2-S1)/1048576 ))MB/min -> $(( (S2-S1)/1048576/60 )) MB/s (nic)"
echo "remaining ~$(( 33135-B ))MB  ETA $(( (33135-B) / ((B-A)/60 + 1) / 60 ))min"
find /root/autodl-tmp/Qwen-Image-2.1 -name '*.safetensors*' -printf '%10s  %f\n' | sort -k2
