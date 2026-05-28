#!/bin/bash
# GitHub に変更を一括プッシュ
# 使い方: bash git_push.sh ["コミットメッセージ"]

MSG="${1:-update: $(date '+%Y-%m-%d %H:%M')}"

cd "$(dirname "$0")"

git add -A
git status --short

echo ""
read -rp "上記の変更をコミット＆プッシュしますか？ [y/N]: " yn
if [[ "$yn" != "y" && "$yn" != "Y" ]]; then
    echo "キャンセルしました"
    exit 0
fi

git commit -m "$MSG"
git push origin main
echo ""
echo "完了: https://github.com/Satoki3016/frr-docker-lab"
