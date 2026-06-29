#!/bin/bash
# 物理実験 + namespace実験 の比較レポート生成
# 使い方: sudo bash scripts/physical2_compare_report.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB_DIR="$(dirname "$SCRIPT_DIR")"
PHYS_DIR="$LAB_DIR/results_physical"
NS_DIR="$LAB_DIR/results"

SEP="═══════════════════════════════════════════════════"

echo "$SEP"
echo "■ フェイルオーバー比較レポート"
echo "$SEP"
echo ""
printf "%-30s %8s %8s %12s %18s\n" \
    "シナリオ" "総数" "ロスト" "ロス率" "推定回復時間"
printf "%-30s %8s %8s %12s %18s\n" \
    "------------------------------" "--------" "--------" "------------" "------------------"

print_row() {
    local label="$1" csv="$2"
    if [ -f "$csv" ]; then
        tail -1 "$csv" | awk -F',' -v lbl="$label" \
            '{printf "%-30s %8s %8s %11s%% %15sms\n", lbl, $2, $3, $4, $5}'
    else
        printf "%-30s %8s\n" "$label" "(未実行)"
    fi
}

# namespace 実験
print_row "NS: normal"        "$NS_DIR/normal/summary.csv"
print_row "NS: failure"       "$NS_DIR/failure/summary.csv"
print_row "NS: failure_rsvp"  "$NS_DIR/failure_rsvp/summary.csv"

echo ""

# 物理実験
print_row "PHYS: normal"        "$PHYS_DIR/normal/summary.csv"
print_row "PHYS: failure"       "$PHYS_DIR/failure/summary.csv"
print_row "PHYS: failure_ospf"  "$PHYS_DIR/failure_ospf/summary.csv"

echo ""
echo "$SEP"
echo ""
echo "対応関係:"
echo "  NS: failure       ↔  PHYS: failure      (静的ECMP, OSPFなし, 1/3ロス継続)"
echo "  NS: failure_rsvp  ↔  PHYS: failure_ospf (動的検知・迂回: rsvp_monitor vs OSPF+BFD)"
echo "  NS: normal        ↔  PHYS: normal        (障害なし, 基準値)"
