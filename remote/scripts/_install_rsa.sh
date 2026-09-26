export PATH=/root/miniconda3/bin:$PATH
RSA="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQDOfbbXAhIrMdXMS1y0DgQHk36r6NUhOqLgIymMX5vVPBAa8pScSzvbZl3iUZI4bsqj8kTEHoa7wDNV0vQzR6K8ouy6Ant2F2tSDvMxaOtrwXNh6CLCJZLUkCyHdb0Z8+sFiuuHoPpEhe7E8lwgmz1Ve4k7yLkVSgMSrSLShcd1oKcJVRnpmm/MrsajgdQVskW9kFXpjiooaUCsPyUVlnaQYzvPvUEFwqQpT7V4125WFD8uDzsMLo2kvh0UPhs42e0UIGFTZW/PdRjI6aibBaERlwcTdqbBN8SiPa9mkjgOKkcR0n40pnkjaSpB+qElH1UBuuK3aLObaVtTi1ogktOr1ldgo8aD6DHJ/nbccOC8LHlqw9Kc1y2eKgt12R0/NWabCFnUWEyuP+SxARfalFCNJKWVCQ77dB0UVJOppdhhxEpzVnlxkpuPzsOAWGL0/uzB3JfNvlUa+P+kOeCf4SnAPjxZKdDWDazKXhdsud0c6RkL0whsR7l0Bpol7dfLNSs= dsh-autodl-tunnel-rsa"

mkdir -p /root/.ssh && chmod 700 /root/.ssh
touch /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys
if grep -qF "dsh-autodl-tunnel-rsa" /root/.ssh/authorized_keys; then
  echo "RSA 已经装过"
else
  echo "$RSA" >> /root/.ssh/authorized_keys
  echo "RSA 已追加"
fi
echo "=== authorized_keys 现有条目 ==="
cut -c1-50 /root/.ssh/authorized_keys
echo "=== 换行/编码检查 ==="
python3 - <<'PY'
data = open('/root/.ssh/authorized_keys','rb').read()
print('bytes:', len(data), 'lines:', data.count(b'\n'), 'has CR:', b'\r' in data)
for i, line in enumerate(data.split(b'\n')):
    if line.strip():
        parts = line.split(None, 2)
        print(f'  line{i}: type={parts[0].decode()} len={len(line)} comment={parts[2].decode()[:40] if len(parts)>2 else "-"}')
PY
