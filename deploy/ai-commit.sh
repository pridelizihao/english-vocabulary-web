#!/usr/bin/env bash
# 用「鲸鱼助手」bot 身份做共同作者提交 —— 就是 README 致谢里那只鲸鱼娘。
# 用法： bash deploy/ai-commit.sh -m "feat(scope): 中文摘要" [-m "正文"] [其它 git commit 参数]
#   参数原样透传给 git commit，额外补一条 Co-authored-by。
set -euo pipefail

# 这几个值必须和 GitHub 上的账号一致：id 错了就不会被归到该账号，只会变成灰色头像。
BOT_LOGIN=deepseek-aibot
BOT_ID=357897862
BOT_NAME="DeepSeek 鲸鱼助手"

exec git commit "$@" --trailer "Co-authored-by: ${BOT_NAME} <${BOT_ID}+${BOT_LOGIN}@users.noreply.github.com>"
