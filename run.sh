#!/bin/bash
# 一括実行スクリプト: セットアップ → 計測 → グラフ生成
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DURATION=${1:-58}

echo "================================================"
echo " frr-docker-lab 一括実行 (計測時間: ${DURATION}秒)"
echo "================================================"

# ----------------------------------------------------------------
# 1. コンテナセットアップ（既存ならスキップ）
# ----------------------------------------------------------------
if ip netns list 2>/dev/null | awk '{print $1}' | grep -qxF "LER_Ingress"; then
    echo "[skip] namespace は既に起動中"
else
    echo "[1/4] namespace 起動..."
    bash "$SCRIPT_DIR/scripts/10_up.sh"
    echo "[2/4] 配線・ルート設定..."
    bash "$SCRIPT_DIR/scripts/20_wire.sh"
    echo "[3/4] QoS (DSCP/WRR) 設定..."
    bash "$SCRIPT_DIR/scripts/30_tc.sh"
    echo "[4/4] MPLS LSP 設定..."
    bash "$SCRIPT_DIR/scripts/50_mpls.sh"
fi

# ----------------------------------------------------------------
# 2. 計測 + グラフ生成
# ----------------------------------------------------------------
echo ""
echo "[計測] UDP送信 + ping 開始..."
bash "$SCRIPT_DIR/scripts/measure.sh" "$DURATION"

echo ""
echo "================================================"
echo " 完了: results/ にグラフが保存されました"
echo "================================================"
ls "$SCRIPT_DIR/results/"*.png 2>/dev/null | sed 's/^/  /'
