export PATH=/root/miniconda3/bin:$PATH
DIR=/root/autodl-tmp/Qwen-Image-2.1
A=$(du -sm $DIR | cut -f1); sleep 90
B=$(du -sm $DIR | cut -f1)
LEFT=$(find $DIR -name '*.incomplete' | wc -l)
echo "delta=$((B-A))MB/90s ($(( (B-A)*10/15 ))MB/min)  now=${B}MB  left_files=${LEFT}"
if [ "$LEFT" -eq 0 ]; then echo COMPLETE; else echo "ETA=$(( (33135-B) / ((B-A)*10/15+1) ))min"; fi
find $DIR -name '*.incomplete' -printf '%10s %f\n'
