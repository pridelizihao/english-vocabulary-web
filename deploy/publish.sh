#!/usr/bin/env bash
# 一次推到两个远端：github（公开镜像）在前，origin（服务器上的裸仓库，部署源）在后。
# 用法： bash deploy/publish.sh [分支，默认 main]
set -euo pipefail

BRANCH=${1:-main}

if git rev-parse --verify --quiet "refs/remotes/github/$BRANCH" >/dev/null; then
  echo "==> 推送 github/$BRANCH"
  git push github "HEAD:$BRANCH"
else
  echo "==> 首次推送 github/$BRANCH"
  git push -u github "HEAD:$BRANCH"
fi

echo "==> 推送 origin/$BRANCH"
git push origin "HEAD:$BRANCH"

echo "完成。服务器上部署： bash /opt/english-vocabulary/deploy/update.sh"
