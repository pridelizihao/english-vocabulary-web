# 部署（Ubuntu + nginx + gunicorn，不用 Docker）

本项目在 Ubuntu 24.04 / nginx 1.24 / Python 3.12 上按下面的流程跑通过，公网用 `http://<服务器IP>/` 访问。
Docker 方式（`docker-compose.yml`）仍保留，但开发机没有 Docker，未实测。

## 目录约定

| 路径 | 用途 |
| --- | --- |
| `/opt/english-vocabulary/backend` | Django 代码（只读，部署时整体覆盖） |
| `/opt/english-vocabulary/venv` | Python 虚拟环境 |
| `/opt/english-vocabulary/.env` | 生产环境变量（`chmod 600`） |
| `/var/lib/english-vocabulary/db.sqlite3` | SQLite 数据库（**备份这个文件**） |
| `/var/lib/english-vocabulary/audio` | 例句语音缓存（可删，会重新生成） |
| `/var/www/english-vocabulary` | 前端 `dist` 静态文件 |

## 首次部署

```bash
# 1. 系统依赖
apt-get update && apt-get install -y nginx python3-venv

# 2. 上传代码（在本地仓库根目录打包，排除本地库和缓存）
tar -czf /tmp/ev.tar.gz --exclude='db.sqlite3*' --exclude=__pycache__ \
  --exclude=staticfiles --exclude='*.pyc' \
  backend data/imports data/samples data/examples.json frontend/dist
scp /tmp/ev.tar.gz root@<服务器IP>:/tmp/

# 3. 服务器上解包 + 依赖
mkdir -p /opt/english-vocabulary /var/lib/english-vocabulary /var/lib/english-vocabulary/audio /var/www/english-vocabulary
tar -xzf /tmp/ev.tar.gz -C /opt/english-vocabulary
cp -r /opt/english-vocabulary/frontend/dist/. /var/www/english-vocabulary/
rm -rf /opt/english-vocabulary/frontend
python3 -m venv /opt/english-vocabulary/venv
/opt/english-vocabulary/venv/bin/pip install -r /opt/english-vocabulary/backend/requirements.txt

# 4. 环境变量（SECRET_KEY 用 python -c "import secrets;print(secrets.token_urlsafe(50))" 生成）
cat > /opt/english-vocabulary/.env <<'EOF'
DJANGO_DEBUG=0
DJANGO_SECRET_KEY=<生成的随机串>
DJANGO_ALLOWED_HOSTS=<服务器IP或域名>
DJANGO_CSRF_TRUSTED_ORIGINS=http://<服务器IP或域名>
DJANGO_DB_PATH=/var/lib/english-vocabulary/db.sqlite3
DJANGO_AUDIO_DIR=/var/lib/english-vocabulary/audio
DJANGO_AUTH_THROTTLE_RATE=10/min
# 邮箱验证码 / 找回密码（不配的话发码接口返回 502）
DJANGO_EMAIL_HOST=smtp.example.com
DJANGO_EMAIL_PORT=465
DJANGO_EMAIL_USER=no-reply@example.com
DJANGO_EMAIL_PASSWORD=<授权码>
DJANGO_EMAIL_USE_SSL=1
DJANGO_EMAIL_USE_TLS=0
DJANGO_DEFAULT_FROM_EMAIL=英语单词记忆 <no-reply@example.com>
EOF
chmod 600 /opt/english-vocabulary/.env

# 4.1 发信自检（可跳过；确认 SMTP 通不通，别等用户收不到码才发现）
set -a && . /opt/english-vocabulary/.env && set +a
cd /opt/english-vocabulary/backend
/opt/english-vocabulary/venv/bin/python manage.py shell -c \
  "from django.conf import settings; from django.core.mail import send_mail; \
   print(send_mail('SMTP 自检', '收到这封就说明发信通了。', settings.DEFAULT_FROM_EMAIL, ['你的邮箱@example.com']))"
# 打印 1 = 已投递到 SMTP 服务器；报错就把错误贴出来看是哪一步（连接 / 认证 / 发件人不符）

# 4.2 用 Brevo 发信（没有域名时的过渡方案）
#   注意三点，都是实测踩过的：
#   1) SMTP 认证要用「SMTP key」(xsmtpsib-...)，账号密码和 API key (xkeysib-...) 都不行；
#      认证失败会报 535 5.7.8。
#   2) Brevo 默认限制「授权 IP」，服务器 IP 没加进去会报 525 5.7.1 Unauthorized IP address。
#      去 https://app.brevo.com/security/authorised_ips 加上服务器公网 IP。
#   3) SMTP 返回 250 只代表 Brevo 收下了，不代表送达：发件人必须在
#      「Senders & IP → Senders」里验证过，否则事件日志里是
#      「error: the sender you used ... is not valid」，用户收不到任何东西。
#      查投递结果：GET https://api.brevo.com/v3/smtp/statistics/events?limit=8
#   服务器连的是 smtp-relay.brevo.com:587（STARTTLS），证书显示走亚洲节点。

# 5. 建库 + 词表 + 后台静态文件
set -a && . /opt/english-vocabulary/.env && set +a
cd /opt/english-vocabulary/backend
/opt/english-vocabulary/venv/bin/python manage.py migrate --noinput
/opt/english-vocabulary/venv/bin/python manage.py seed_dictionaries
/opt/english-vocabulary/venv/bin/python manage.py seed_wordlists
/opt/english-vocabulary/venv/bin/python manage.py collectstatic --noinput
/opt/english-vocabulary/venv/bin/python manage.py createsuperuser
chown -R www-data:www-data /var/lib/english-vocabulary

# 6. 服务
cp deploy/english-vocabulary.service /etc/systemd/system/
cp deploy/nginx.conf /etc/nginx/sites-available/english-vocabulary
ln -sf /etc/nginx/sites-available/english-vocabulary /etc/nginx/sites-enabled/english-vocabulary
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl daemon-reload
systemctl enable --now english-vocabulary
systemctl reload nginx
```

访问 `http://<服务器IP>/`，后台在 `/admin/`。

## 更新一版（git 方式，推荐）

服务器上 `/opt/english-vocabulary` 是一个 git 工作区，remote `origin` 指向服务器上的裸库
`/srv/git/english-vocabulary.git`。开发机把 `origin` 配成同一个裸库，于是流程就是：

```bash
# 本地：提交并推送
git push origin main

# 服务器：一条命令（拉代码 → 备份库 → 迁移 → collectstatic → 铺前端 → 重启 → 自检）
bash /opt/english-vocabulary/deploy/update.sh
```

`update.sh` 会做的事：

1. `git fetch` + `merge --ff-only`（不做合并，冲突就停）；
2. 用 sqlite backup API 把生产库备份到 `/var/backups/english-vocabulary/`，只留最近 10 份；
3. `migrate --noinput` + `collectstatic`；
4. `rsync -a --delete frontend/dist/ → /var/www/english-vocabulary/`（旧资源自动清掉）；
5. 重启 `english-vocabulary` 并检查 `/api/auth/csrf` 是否 200；
6. 脚本失败即退出，末尾会打印回滚用的库文件路径。

**为什么 `frontend/dist` 入库**：部署机不装 Node 构建链（只跑 gunicorn + nginx），
`git pull` 直接拿到构建好的 js/css，服务器上零构建。代价是每次改前端要本地 `npm run build` 后再提交。

### 首次把老服务器接进 git（一次性）

```bash
# 服务器：建裸库
mkdir -p /srv/git && git init --bare /srv/git/english-vocabulary.git

# 服务器：把部署目录变成工作区（venv/.env/staticfiles 不在仓库里，不受影响）
cd /opt/english-vocabulary
git init -q
git remote add origin /srv/git/english-vocabulary.git
git fetch origin
git checkout -B main origin/main     # 注意：会覆盖仓库里跟踪的文件，先确认 /var/www 有备份

# 开发机：加 remote 并推送
git remote add origin ssh://root@<服务器IP>/srv/git/english-vocabulary.git
git push -u origin main
```

> 从裸库 checkout 会覆盖同名文件；`.env`、`venv/`、`backend/staticfiles/` 不在版本库里，
> 不会被改动。第一次操作前建议先 `cp -a /opt/english-vocabulary /opt/english-vocabulary.bak`。

## 更新一版（手工方式，备用）

网络/权限不方便用 git 时，回退到打包 + scp：

```bash
# 0. 迁移前先备份生产库
mkdir -p /var/backups/english-vocabulary
/opt/english-vocabulary/venv/bin/python - <<'PY'
import datetime, sqlite3
target = f"/var/backups/english-vocabulary/before-update-{datetime.datetime.now():%Y%m%d-%H%M%S}.sqlite3"
source = sqlite3.connect('/var/lib/english-vocabulary/db.sqlite3')
sink = sqlite3.connect(target)
source.backup(sink)
sink.close()
source.close()
print(target)
PY

# 本地构建前端 → 打包 → scp 到 /tmp/ev.tar.gz 后：
tar -xzf /tmp/ev.tar.gz -C /opt/english-vocabulary
rsync -a --delete /opt/english-vocabulary/frontend/dist/ /var/www/english-vocabulary/
set -a && . /opt/english-vocabulary/.env && set +a
cd /opt/english-vocabulary/backend
/opt/english-vocabulary/venv/bin/python manage.py migrate --noinput
/opt/english-vocabulary/venv/bin/python manage.py collectstatic --noinput
systemctl restart english-vocabulary
```


前端 `dist/assets/*` 带内容哈希，覆盖后直接刷新即可，不用清 nginx 缓存。

## 运维

```bash
systemctl status english-vocabulary     # 服务状态
journalctl -u english-vocabulary -f     # 实时日志（含访问日志）
nginx -t && systemctl reload nginx      # 改完 nginx 配置先测再 reload

# 备份数据库（服务器没装 sqlite3 CLI，用 venv 里的 Python；建议加进 cron 或阿里云快照）
/opt/english-vocabulary/venv/bin/python - <<'PY'
import datetime, os, sqlite3
os.makedirs('/var/backups', exist_ok=True)
target = f"/var/backups/ev-{datetime.date.today():%F}.sqlite3"
source = sqlite3.connect('/var/lib/english-vocabulary/db.sqlite3')
sink = sqlite3.connect(target)
source.backup(sink)
sink.close()
source.close()
print(target)
PY
```

## 注意

- 站点是公网可访问、**注册接口开放**的；只想自己用时，在 nginx 上加 Basic Auth 或收紧注册。
- 没有配 HTTPS。有域名后：`apt install certbot python3-certbot-nginx && certbot --nginx -d 你的域名`，再把 `.env` 里的 `DJANGO_CSRF_TRUSTED_ORIGINS` 改成 https 地址并加 `DJANGO_USE_X_FORWARDED_PROTO=1`。
- `DJANGO_DEBUG=0` 时 Django 不提供静态文件，后台样式靠 `collectstatic` + nginx 的 `/static/` 别名。
- 词表已随镜像 seed（3500 → 3498 词、5000 → 4998 词，重复词会合并）；重跑 `seed_wordlists` 是幂等的。
