#!/usr/bin/env bash
# 服务器端一键更新：git pull → 备份库 → 迁移 → 收静态 → 铺前端 → 重启 → 自检
# 用法： bash /opt/english-vocabulary/deploy/update.sh
set -euo pipefail

APP_DIR=/opt/english-vocabulary
WEB_DIR=/var/www/english-vocabulary
BACKUP_DIR=/var/backups/english-vocabulary
PY="$APP_DIR/venv/bin/python"
SERVICE=english-vocabulary
REPO_BRANCH=${REPO_BRANCH:-main}

say() { printf '\n\033[1;35m==> %s\033[0m\n' "$1"; }

cd "$APP_DIR"

say "1/7 拉取代码"
BEFORE=$(git rev-parse --short HEAD)
git fetch --prune origin
git checkout -q "$REPO_BRANCH"
git merge --ff-only "origin/$REPO_BRANCH"
AFTER=$(git rev-parse --short HEAD)
echo "   $BEFORE -> $AFTER"
git --no-pager log --oneline -3

if [ "$BEFORE" = "$AFTER" ]; then
  echo "   没有新提交，仍继续走完流程（部署幂等）"
fi

say "2/7 备份数据库"
mkdir -p "$BACKUP_DIR"
BACKUP="$BACKUP_DIR/before-update-$(date +%Y%m%d-%H%M%S).sqlite3"
DB_PATH=$(sed -n 's/^DJANGO_DB_PATH=//p' "$APP_DIR/.env" | tr -d '"' | tail -1)
DB_PATH=${DB_PATH:-/var/lib/english-vocabulary/db.sqlite3}
"$PY" - "$DB_PATH" "$BACKUP" <<'PY'
import sqlite3, sys
src_path, dst_path = sys.argv[1], sys.argv[2]
src = sqlite3.connect(src_path)
dst = sqlite3.connect(dst_path)
with dst:
    src.backup(dst)
dst.close(); src.close()
print(f'   {dst_path}')
PY
# 只保留最近 10 份
ls -1t "$BACKUP_DIR"/before-update-*.sqlite3 2>/dev/null | tail -n +11 | xargs -r rm -f

say "3/7 读取环境变量"
set -a
# shellcheck disable=SC1090
. "$APP_DIR/.env"
set +a
echo "   DJANGO_DEBUG=$DJANGO_DEBUG  DB=$DJANGO_DB_PATH"

say "4/7 数据库迁移"
cd "$APP_DIR/backend"
"$PY" manage.py migrate --noinput
"$PY" manage.py collectstatic --noinput -v 0

say "5/7 部署前端产物"
if [ -d "$APP_DIR/frontend/dist" ]; then
  rsync -a --delete "$APP_DIR/frontend/dist/" "$WEB_DIR/"
  echo "   $(ls -1 "$WEB_DIR/assets" | tr '\n' ' ')"
else
  echo "   !! frontend/dist 不存在，跳过（前端会停在旧版本）" >&2
fi

say "6/7 重启服务"
systemctl restart "$SERVICE"
sleep 3
systemctl is-active "$SERVICE"

say "7/7 自检"
HOST_HEADER=$(sed -n 's/^DJANGO_ALLOWED_HOSTS=//p' "$APP_DIR/.env" | tr -d '"' | cut -d',' -f1)
[ -n "$HOST_HEADER" ] || HOST_HEADER=127.0.0.1
CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "Host: $HOST_HEADER" http://127.0.0.1:8000/api/auth/csrf || true)
echo "   /api/auth/csrf -> $CODE"
if [ "$CODE" != "200" ]; then
  echo "   !! 接口自检失败，看日志： journalctl -u $SERVICE -n 50" >&2
  exit 1
fi

say "完成"
echo "   回滚旧库： cp $BACKUP <数据库路径> && systemctl restart $SERVICE"
