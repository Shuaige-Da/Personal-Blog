# RainWave 生产部署配置

此目录保存 RainWave 当前生产架构使用的可审计配置模板：

- `systemd/rainwave.service`：以 `www-data` 运行 Gunicorn，使用 Unix Socket，并启用 Systemd 沙箱和资源限制。
- `nginx/rainwave.conf`：提供 HTTPS、静态资源、持久化上传目录和反向代理。
- `nginx/rainwave-security.conf`：提供共享请求限速、连接数限制和隐藏版本号。
- `ssh/00-rainwave-hardening.conf`：验证密钥登录后优先关闭 SSH 密码登录。
- `fail2ban/rainwave.local`：保护 SSH 和触发 Nginx 限速的来源地址。
- `journald/60-rainwave-retention.conf`：限制系统日志磁盘占用。
- `logrotate/btmp`：压缩并轮转失败登录记录，避免暴力扫描持续占用磁盘。

服务器约定：

```text
/var/www/rainwave-current                 当前版本软链接
/var/www/rainwave-releases/<release>      不可变代码与独立虚拟环境
/var/www/rainwave-shared/uploads          持久化用户上传内容
/etc/rainwave/rainwave.env                仅服务器保存的生产密钥
/run/rainwave/gunicorn.sock               Nginx 与 Gunicorn 的本地套接字
```

不要在未验证 SSH 公钥登录前应用 SSH 加固配置，也不要把 `.env`、数据库或上传内容提交到 Git。
