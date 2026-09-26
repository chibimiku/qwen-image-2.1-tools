export PATH=/root/miniconda3/bin:$PATH
KEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDutq52vN0/HJuL9sICFYgxw82vrDvvO5/lPl08lPQ7T dsh-autodl-tunnel"

mkdir -p /root/.ssh
chmod 700 /root/.ssh
touch /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys

echo '=== 安装前 ==='
wc -l /root/.ssh/authorized_keys
if grep -qF "dsh-autodl-tunnel" /root/.ssh/authorized_keys 2>/dev/null; then
  echo "已经装过了，跳过"
else
  echo "$KEY" >> /root/.ssh/authorized_keys
  echo "已追加"
fi
echo '=== 安装后 ==='
wc -l /root/.ssh/authorized_keys
echo '--- 文件尾部 ---'
tail -2 /root/.ssh/authorized_keys | cut -c1-80
echo '--- 权限 ---'
ls -la /root/.ssh/
echo '=== sshd 配置全貌（关键项）==='
grep -vE '^\s*#|^\s*$' /etc/ssh/sshd_config | head -30
