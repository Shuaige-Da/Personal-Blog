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
/var/www/rainwave-shared/hermes-attachments  Agent 私有附件（不能由 Nginx 公开）
/etc/rainwave/rainwave.env                仅服务器保存的生产密钥
/run/rainwave/gunicorn.sock               Nginx 与 Gunicorn 的本地套接字
```

音频上传依赖 `ffmpeg` 和 `ffprobe`。Debian/Ubuntu 可执行
`sudo apt install ffmpeg`，部署前用 `ffmpeg -version`、`ffprobe -version`
确认二者可用。创建共享目录后，将上传目录和 Agent 附件目录都授权给
`www-data`，并在生产环境文件中设置 `HERMES_ATTACHMENT_FOLDER`。

首次升级前先备份数据库和 `/var/www/rainwave-shared/uploads`。应用启动会通过
现有 `db.create_all()` 创建 `audio_playback_variant` 与 `hermes_attachment` 表；
随后在当前版本虚拟环境中执行 `flask --app backend.core.app:create_app
backfill-audio-variants`，为旧音频生成无损 WAV 副本。

Nginx 的静态文件模块默认支持 Range 请求。上线后应分别对原音频和 WAV 执行
`curl -I -H "Range: bytes=0-1023" <URL>`，确认响应为 `206 Partial Content`。
流式 Agent 接口单独关闭了代理缓冲，其余页面继续使用常规代理设置。

不要在未验证 SSH 公钥登录前应用 SSH 加固配置，也不要把 `.env`、数据库或上传内容提交到 Git。
