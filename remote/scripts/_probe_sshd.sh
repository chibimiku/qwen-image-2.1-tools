export PATH=/root/miniconda3/bin:$PATH
echo '=== sshd 是否允许公钥登录 ==='
grep -iE '^(PubkeyAuthentication|AuthorizedKeysFile|PasswordAuthentication|PermitRootLogin)' /etc/ssh/sshd_config 2>/dev/null
echo '--- 是否存在 authorized_keys ---'
ls -la /root/.ssh/ 2>/dev/null || echo '没有 /root/.ssh'
echo '--- 现在里面有几把钥匙 ---'
wc -l /root/.ssh/authorized_keys 2>/dev/null || echo '0（还没有 authorized_keys）'
