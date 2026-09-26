export PATH=/root/miniconda3/bin:$PATH
echo '=== sshd_config.d 里的覆盖项 ==='
for f in /etc/ssh/sshd_config.d/*.conf; do echo "--- $f"; cat "$f"; done 2>/dev/null
echo '=== sshd 实际生效配置 ==='
sshd -T 2>/dev/null | grep -iE 'pubkey|authorizedkeys|permitrootlogin|strictmodes|authenticationmethods' || echo '(sshd -T 不可用)'
echo '=== sshd 版本 ==='
sshd -V 2>&1 | head -2 || dpkg -l openssh-server | tail -1
echo '=== /root 权限（StrictModes 会查这个）==='
ls -ld /root /root/.ssh /root/.ssh/authorized_keys
echo '=== 认证日志（最后几条）==='
tail -30 /var/log/auth.log 2>/dev/null | grep -iE 'sshd|auth' | tail -12 || echo '没有 auth.log'
journalctl -u ssh -n 12 --no-pager 2>/dev/null | tail -12 || true
echo '=== 是否有 ssh-agent / 别的认证方式线索 ==='
cat /etc/ssh/sshd_config.d/*.conf 2>/dev/null | grep -i authorized || echo '(d 目录里没有 authorized 相关)'
