#!/bin/bash
# 3シナリオ (normal / failure / failure_reroute) を順番に実行し、
# 終了後に比較グラフを生成する。
#
# 使い方:
#   sudo bash scripts/run_all_scenarios.sh [duration] [tag]
#   sudo bash scripts/run_all_scenarios.sh 60 20260706_experiment
#   sudo bash scripts/run_all_scenarios.sh 30 test   # 短縮テスト

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

DURATION="${1:-60}"
TAG="${2:-$(date +%Y%m%d)_experiment}"

echo "════════════════════════════════════════"
echo "  FRR OSPF-SR 3シナリオ一括実行"
echo "  各 ${DURATION}s × 3 シナリオ"
echo "  タグ: ${TAG}"
echo "════════════════════════════════════════"

for SCENARIO in normal failure failure_reroute; do
    echo ""
    echo "════════════════════════════════════════"
    echo "  シナリオ: ${SCENARIO}"
    echo "════════════════════════════════════════"
    sudo bash "${SCRIPT_DIR}/frr_dscp_te.sh"
    bash "${SCRIPT_DIR}/frr_measure.sh" "$DURATION" "$SCENARIO" "$TAG"
    echo "  [完了] ${SCENARIO}"
    # 次のシナリオ前に OSPF が完全に安定するまで待機
    sleep 5
done

echo ""
echo "════════════════════════════════════════"
echo "  全3シナリオ完了 — 比較グラフ生成"
echo "════════════════════════════════════════"

PLOT_SCRIPT="${LAB_DIR}/results/frr/plot_frr.py"
FRR_BASE="${LAB_DIR}/results/frr/${TAG}"

if [ -n "$SUDO_USER" ]; then
    sudo -u "$SUDO_USER" python3 "$PLOT_SCRIPT" --base "$FRR_BASE"
else
    python3 "$PLOT_SCRIPT" --base "$FRR_BASE"
fi

echo ""
echo "グラフ出力先: ${FRR_BASE}/figures/"
echo "════════════════════════════════════════"
