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
mkdir -p /opt/english-vocabulary /var/lib/english-vocabulary /var/www/english-vocabulary
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
DJANGO_AUTH_THROTTLE_RATE=10/min
EOF
chmod 600 /opt/english-vocabulary/.env

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

## 更新一版

```bash
# 0. 迁移前先备份生产库（有数据之后每次更新都建议做）
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

# 本地重新构建前端并打包（同上），scp 到 /tmp/ev.tar.gz 后：
tar -xzf /tmp/ev.tar.gz -C /opt/english-vocabulary
rm -rf /var/www/english-vocabulary/*
cp -r /opt/english-vocabulary/frontend/dist/. /var/www/english-vocabulary/
rm -rf /opt/english-vocabulary/frontend
/opt/english-vocabulary/venv/bin/pip install -q -r /opt/english-vocabulary/backend/requirements.txt
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
