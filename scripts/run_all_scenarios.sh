#!/bin/bash
# 3シナリオ (normal / failure / failure_rsvp) を順番に実行し、
# 終了後に比較グラフを生成する。
#
# 使い方:
#   sudo bash scripts/run_all_scenarios.sh          # 各60秒
#   sudo bash scripts/run_all_scenarios.sh 30       # 各30秒 (短縮テスト)

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DURATION="${1:-60}"

echo "========================================"
echo "  3シナリオ一括実行 (各 ${DURATION}s)"
echo "  normal → failure → failure_rsvp"
echo "========================================"

for SCENARIO in normal failure failure_rsvp; do
    echo ""
    echo "========================================"
    echo "  シナリオ: ${SCENARIO}"
    echo "========================================"
    bash "${SCRIPT_DIR}/measure.sh" "$DURATION" "$SCENARIO"
    echo ""
    echo "  [完了] ${SCENARIO}"
    sleep 3
done

echo ""
echo "========================================"
echo "  全3シナリオ完了 — 比較グラフ生成"
echo "========================================"

LAB_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PLOT_SCRIPT="${LAB_DIR}/results/plot_rx.py"

if [ -n "$SUDO_USER" ]; then
    sudo -u "$SUDO_USER" python3 "$PLOT_SCRIPT"
else
    python3 "$PLOT_SCRIPT"
fi

echo ""
echo "グラフ出力先: ${LAB_DIR}/results/figures/"
echo "========================================"
