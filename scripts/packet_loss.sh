#!/bin/bash
# 各ルーターのパケットロス統計（優先度クラス別）を表示
#
# 使い方: bash scripts/packet_loss.sh [results_dir]
# 出力:   <results_dir>/packet_loss.csv

RESULTS_DIR="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lab_config.sh"

# HTB クラス別の sent/dropped を取得
# 引数: namespace, interface, classid (例: 1:1)
get_class_stats() {
    local ns=$1 dev=$2 classid=$3
    ip netns exec "$ns" tc -s class show dev "$dev" classid "$classid" 2>/dev/null
}

# "Sent X bytes Y pkt (dropped Z, ...)" から sent_pkt と dropped を抽出
parse_class_loss() {
    local stats=$1
    local sent dropped
    sent=$(echo    "$stats" | grep -oP '\b\d+ pkt'      | head -1 | awk '{print $1}')
    dropped=$(echo "$stats" | grep -oP 'dropped \K\d+'  | head -1)
    sent=${sent:-0}; dropped=${dropped:-0}
    if [ "$sent" -gt 0 ] || [ "$dropped" -gt 0 ]; then
        local total=$(( sent + dropped ))
        local loss_pct
        loss_pct=$(awk "BEGIN {printf \"%.2f\", $dropped / ($total > 0 ? $total : 1) * 100}")
    else
        loss_pct="0.00"
    fi
    echo "$sent $dropped $loss_pct"
}

# ingress policing の sent/dropped を取得
get_ingress_stats() {
    local ns=$1 dev=$2
    ip netns exec "$ns" tc -s filter show dev "$dev" parent ffff: 2>/dev/null
}

parse_ingress_loss() {
    local stats=$1
    local sent dropped
    sent=$(echo    "$stats" | grep -oP 'Sent \K\d+'     | head -1)
    dropped=$(echo "$stats" | grep -oP 'dropped \K\d+'  | head -1)
    sent=${sent:-0}; dropped=${dropped:-0}
    local total=$(( sent + dropped ))
    local loss_pct
    loss_pct=$(awk "BEGIN {printf \"%.2f\", $dropped / ($total > 0 ? $total : 1) * 100}")
    echo "$sent $dropped $loss_pct"
}

# クラス ID と優先度名の対応
# 1:1=AF41(高), 1:2=AF42(中), 1:3=AF43(低)
CLASS_IDS=("1:1" "1:2" "1:3")
CLASS_NAMES=("AF41(高)" "AF42(中)" "AF43(低)")

echo ""
echo "================================================================"
echo " パケットロス統計（優先度クラス別）"
echo "================================================================"

CSV="node,interface,direction,class,sent_pkts,dropped_pkts,loss_pct"

print_class_row() {
    local node=$1 dev=$2 dir=$3 cls=$4 sent=$5 dropped=$6 loss=$7
    printf "    %-10s sent=%-8s dropped=%-6s loss=%s%%\n" \
        "$cls" "$sent" "$dropped" "$loss"
    CSV="$CSV
$node,$dev,$dir,$cls,$sent,$dropped,$loss"
}

# ----------------------------------------------------------------
# LER_Ingress → CoreRouter (WRR HTB)
# ----------------------------------------------------------------
echo ""
echo "--- LER_Ingress_ns egress (WRR HTB) ---"
for dev in leri-cr1 leri-cr2 leri-cr3; do
    echo "  $dev:"
    for i in 0 1 2; do
        classid="${CLASS_IDS[$i]}"
        name="${CLASS_NAMES[$i]}"
        stats=$(get_class_stats LER_Ingress_ns "$dev" "$classid")
        read -r sent dropped loss <<< "$(parse_class_loss "$stats")"
        print_class_row "LER_Ingress_ns" "$dev" "egress" "$name" "$sent" "$dropped" "$loss"
    done
done

# ----------------------------------------------------------------
# CoreRouter → LER_Egress (WRR HTB)
# ----------------------------------------------------------------
echo ""
echo "--- CoreRouter_ns egress (WRR HTB) ---"
for i in 1 2 3; do
    dev="cr${i}-lere"
    echo "  CoreRouter${i}_ns $dev:"
    for j in 0 1 2; do
        classid="${CLASS_IDS[$j]}"
        name="${CLASS_NAMES[$j]}"
        stats=$(get_class_stats "CoreRouter${i}_ns" "$dev" "$classid")
        read -r sent dropped loss <<< "$(parse_class_loss "$stats")"
        print_class_row "CoreRouter${i}_ns" "$dev" "egress" "$name" "$sent" "$dropped" "$loss"
    done
done

# ----------------------------------------------------------------
# LER_Ingress ingress policing (クラス分けなし・NIC ごと)
# ----------------------------------------------------------------
echo ""
echo "--- LER_Ingress_ns ingress policing ---"
declare -A DEV_CLASS=(
    ["enp23s0f1np1"]="AF41(高)"
    ["enp179s0f1np1"]="AF42(中)"
    ["enp5s0f1"]="AF43(低)"
)
for dev in enp23s0f1np1 enp179s0f1np1 enp5s0f1; do
    cls="${DEV_CLASS[$dev]}"
    stats=$(get_ingress_stats LER_Ingress_ns "$dev")
    read -r sent dropped loss <<< "$(parse_ingress_loss "$stats")"
    echo "  $dev ($cls):"
    print_class_row "LER_Ingress_ns" "$dev" "ingress" "$cls" "$sent" "$dropped" "$loss"
done

echo ""
echo "================================================================"

# CSV 保存
if [ -n "$RESULTS_DIR" ]; then
    echo "$CSV" > "$RESULTS_DIR/packet_loss.csv"
    echo "保存: $RESULTS_DIR/packet_loss.csv"
fi
