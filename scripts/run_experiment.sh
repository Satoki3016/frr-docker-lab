#!/bin/bash
# 一括実験スクリプト — セットアップから3シナリオ計測・グラフ生成まで全自動
#
# 使い方:
#   sudo bash scripts/run_experiment.sh [duration] [tag]
#
# 引数:
#   duration : 各シナリオの計測秒数 (デフォルト: 60)
#   tag      : 結果フォルダ名 (デフォルト: 今日の日付_25G_veth)
#
# 例:
#   sudo bash scripts/run_experiment.sh
#   sudo bash scripts/run_experiment.sh 60 20260701_25G_new

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lab_config.sh"

DURATION="${1:-60}"
TAG="${2:-$(date +%Y%m%d)_25G_veth}"
RESULTS_BASE="$(cd "$SCRIPT_DIR/.." && pwd)/results/frr/$TAG"

echo "████████████████████████████████████████████"
echo "  一括実験"
echo "  計測時間 : ${DURATION}s × 3シナリオ"
echo "  結果タグ : ${TAG}"
echo "  TX1=${TX1_RATE}  TX2=${TX2_RATE}  TX3=${TX3_RATE}  CR=${CR1_BW}"
echo "████████████████████████████████████████████"
echo ""

# ── [1] コンテナ起動 ─────────────────────────────────────────────────
echo "▶ [1/5] コンテナ起動 & OSPF-SR セットアップ"
bash "$SCRIPT_DIR/frr_all_up.sh"
echo ""

# ── [2] OSPF 収束待ち ────────────────────────────────────────────────
echo "▶ [2/5] OSPF 収束待ち (最大60秒)"
OSPF_TIMEOUT=60
elapsed=0
while true; do
    full_count=$(docker exec frr-LER_Ingress vtysh -c 'show ip ospf neighbor' 2>/dev/null \
        | grep -c 'Full/' || true)
    if [ "$full_count" -ge 3 ]; then
        echo "  [ok] OSPF Full × ${full_count} (${elapsed}s)"
        break
    fi
    if [ "$elapsed" -ge "$OSPF_TIMEOUT" ]; then
        echo "  [warn] OSPF 収束タイムアウト (Full=${full_count}) — 続行します"
        break
    fi
    printf "\r  Full=%d/3 ... %ds" "$full_count" "$elapsed"
    sleep 2
    elapsed=$(( elapsed + 2 ))
done
echo ""

# ── [3-5] 3シナリオ計測 ──────────────────────────────────────────────
SCENARIOS=(normal failure failure_reroute)
STEP=3
for SCENARIO in "${SCENARIOS[@]}"; do
    echo "▶ [${STEP}/5] シナリオ: ${SCENARIO}"
    bash "$SCRIPT_DIR/frr_measure.sh" "$DURATION" "$SCENARIO" "$TAG"
    echo ""
    STEP=$(( STEP + 1 ))
    # 次シナリオ前にコンテナ状態をリセット
    if [ "$SCENARIO" != "failure_reroute" ]; then
        docker exec LER_Ingress ip link set leri-cr1 up 2>/dev/null || true
        sleep 2
    fi
done

# ── 完了 ─────────────────────────────────────────────────────────────
echo "████████████████████████████████████████████"
echo "  完了"
echo "  結果: $RESULTS_BASE"
echo "  グラフ: $RESULTS_BASE/figures/"
echo "████████████████████████████████████████████"
