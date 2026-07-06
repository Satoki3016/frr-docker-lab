#!/bin/bash
# TX 送信レート 対話式設定メニュー
#
# 使い方: bash scripts/menu_tx.sh
#
# 期待スループット計算ロジック:
#   HTB quantum = AF41:AF42:AF43 = 4:2:1 (WRR_HI:WRR_ME:WRR_LO × 9000 bytes)
#   AF41 SP quantum share = 4/7 × CR_BW
#   iperf3 は -P 4 で4ストリーム送信するため 総TX = 4 × TX_RATE
#
#   AF41 総TX ≤ SP share → AF41 全量通過、残余を AF42:AF43 = 2:1 で分配
#   AF41 総TX >  SP share → AF41 は 4/7×CR で頭打ち、残余 3/7 を 2:1 で分配

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/lab_config.sh"

# ── レート変換 ────────────────────────────────────────────────────────
# "3G"→3000, "3.5G"→3500, "130M"→130
rate_to_mbps() {
    awk -v r="$(echo "$1" | tr '[:upper:]' '[:lower:]')" '
    BEGIN {
        n = r + 0
        if (r ~ /g/) print int(n * 1000)
        else if (r ~ /m/) print int(n)
        else if (r ~ /k/) print int(n / 1000)
        else print int(n)
    }'
}

# 12000→"12.0G", 8667→"8.7G", 520→"520M"
to_disp() {
    awk -v m="$1" 'BEGIN {
        if (m >= 1000) printf "%.1fG", m/1000
        else printf "%dM", m
    }'
}

# ── 期待スループット計算 ──────────────────────────────────────────────
# 引数: cr_mbps tx1_mbps tx2_mbps tx3_mbps
# 出力: "af41_rx af42_rx af43_rx af41_loss af42_loss af43_loss"
calc_expected() {
    awk -v cr="$1" -v t1="$2" -v t2="$3" -v t3="$4" '
    BEGIN {
        sp = cr * 4 / 7          # AF41 HTB SP quantum share
        a1 = t1 * 4              # 4 parallel iperf3 streams
        a2 = t2 * 4
        a3 = t3 * 4
        if (a1 <= sp) { r1 = a1; rem = cr - a1 }
        else           { r1 = sp; rem = cr * 3 / 7 }
        r2 = rem * 2 / 3         # WRR ME:LO = 2:1
        r3 = rem * 1 / 3
        l1 = (a1 > 0 && a1 > r1) ? int((a1 - r1) / a1 * 100) : 0
        l2 = (a2 > 0 && a2 > r2) ? int((a2 - r2) / a2 * 100) : 0
        l3 = (a3 > 0 && a3 > r3) ? int((a3 - r3) / a3 * 100) : 0
        printf "%.0f %.0f %.0f %d %d %d\n", r1, r2, r3, l1, l2, l3
    }'
}

# ── lab_config.sh 該当行を上書き ─────────────────────────────────────
update_config() {
    local t1=$1 t2=$2 t3=$3 cr=$4
    sed -i "s|^TX1_RATE=.*|TX1_RATE=\"\${TX1_RATE:-${t1}}\"|" "$CONFIG_FILE"
    sed -i "s|^TX2_RATE=.*|TX2_RATE=\"\${TX2_RATE:-${t2}}\"|" "$CONFIG_FILE"
    sed -i "s|^TX3_RATE=.*|TX3_RATE=\"\${TX3_RATE:-${t3}}\"|" "$CONFIG_FILE"
    sed -i "s|^CR1_BW=.*|CR1_BW=\"\${CR1_BW:-${cr}}\"|" "$CONFIG_FILE"
    sed -i "s|^CR2_BW=.*|CR2_BW=\"\${CR2_BW:-${cr}}\"|" "$CONFIG_FILE"
    sed -i "s|^CR3_BW=.*|CR3_BW=\"\${CR3_BW:-${cr}}\"|" "$CONFIG_FILE"
}

# ── プリセット定義（名前のスペースを避けるため個別配列） ─────────────
PNAME=("軽量テスト" "標準 25G" "AF41フル活用")
PCR=("1G"   "25G"  "25G")
PTX1=("130M" "3G"  "3.5G")
PTX2=("1G"   "15G" "20G")
PTX3=("1G"   "15G" "20G")
PRESET_COUNT=${#PNAME[@]}

# ── プリセット1件を2行で表示 ──────────────────────────────────────────
# print_preset idx cur_cr cur_tx1 cur_tx2 cur_tx3
print_preset() {
    local n=$1 cur_cr=$2 cur_t1=$3 cur_t2=$4 cur_t3=$5
    local i=$(( n - 1 ))
    local name="${PNAME[$i]}" cr="${PCR[$i]}" tx1="${PTX1[$i]}" tx2="${PTX2[$i]}" tx3="${PTX3[$i]}"

    local cr_m tx1_m tx2_m tx3_m
    cr_m=$(rate_to_mbps "$cr")
    tx1_m=$(rate_to_mbps "$tx1")
    tx2_m=$(rate_to_mbps "$tx2")
    tx3_m=$(rate_to_mbps "$tx3")

    read -r r1 r2 r3 l1 l2 l3 <<< "$(calc_expected "$cr_m" "$tx1_m" "$tx2_m" "$tx3_m")"

    local total=$(( (tx1_m + tx2_m + tx3_m) * 4 ))
    local ratio; ratio=$(awk -v t=$total -v c=$cr_m 'BEGIN{printf "%.1f",t/c}')

    local mark=""
    if [ "$cr" = "$cur_cr" ] && [ "$tx1" = "$cur_t1" ] && \
       [ "$tx2" = "$cur_t2" ] && [ "$tx3" = "$cur_t3" ]; then
        mark=" ←現在"
    fi

    printf "  %d) %-14s CR=%-6s TX1=%-6s TX2=%-6s TX3=%-6s [%sx]%s\n" \
        "$n" "$name" "$(to_disp $cr_m)" "$(to_disp $tx1_m)" \
        "$(to_disp $tx2_m)" "$(to_disp $tx3_m)" "$ratio" "$mark"
    printf "     %-14s AF41 %-7s(%2d%%)  AF42 %-7s(%2d%%)  AF43 %-7s(%2d%%)\n" \
        "" "$(to_disp $r1)" $l1 "$(to_disp $r2)" $l2 "$(to_disp $r3)" $l3
}

# ── 入力バリデーション ────────────────────────────────────────────────
validate_rate() {
    echo "$1" | grep -qiE '^[0-9]+(\.[0-9]+)?[GMK]$'
}

# ── カスタム入力 ──────────────────────────────────────────────────────
custom_input() {
    local cur_cr=$1 cur_t1=$2 cur_t2=$3 cur_t3=$4
    local input

    echo ""
    echo "  ─── カスタム入力 ──────────────────────────────"
    echo "  形式例: 3G / 15G / 3.5G / 130M"
    echo "  Enter で現在値を維持"
    echo ""

    printf "  CR_BW (現在: %s): " "$cur_cr"
    read -r input
    if [ -z "$input" ]; then NEW_CR="$cur_cr"
    elif validate_rate "$input"; then NEW_CR="$input"
    else echo "  [!] 無効 → 現在値を維持"; NEW_CR="$cur_cr"; fi

    local sp_d; sp_d=$(to_disp $(( $(rate_to_mbps "$NEW_CR") * 4 / 7 )))
    printf "  TX1 AF41/SP (現在: %s, 損失なし上限 %s/stream): " "$cur_t1" "$sp_d"
    read -r input
    if [ -z "$input" ]; then NEW_TX1="$cur_t1"
    elif validate_rate "$input"; then NEW_TX1="$input"
    else echo "  [!] 無効 → 現在値を維持"; NEW_TX1="$cur_t1"; fi

    printf "  TX2 AF42/WRR (現在: %s): " "$cur_t2"
    read -r input
    if [ -z "$input" ]; then NEW_TX2="$cur_t2"
    elif validate_rate "$input"; then NEW_TX2="$input"
    else echo "  [!] 無効 → 現在値を維持"; NEW_TX2="$cur_t2"; fi

    printf "  TX3 AF43/WRR (現在: %s): " "$cur_t3"
    read -r input
    if [ -z "$input" ]; then NEW_TX3="$cur_t3"
    elif validate_rate "$input"; then NEW_TX3="$input"
    else echo "  [!] 無効 → 現在値を維持"; NEW_TX3="$cur_t3"; fi
}

# ── 適用プレビュー ────────────────────────────────────────────────────
show_preview() {
    local cr_m tx1_m tx2_m tx3_m
    cr_m=$(rate_to_mbps "$NEW_CR")
    tx1_m=$(rate_to_mbps "$NEW_TX1")
    tx2_m=$(rate_to_mbps "$NEW_TX2")
    tx3_m=$(rate_to_mbps "$NEW_TX3")

    read -r r1 r2 r3 l1 l2 l3 <<< "$(calc_expected "$cr_m" "$tx1_m" "$tx2_m" "$tx3_m")"

    local total=$(( (tx1_m + tx2_m + tx3_m) * 4 ))
    local ratio; ratio=$(awk -v t=$total -v c=$cr_m 'BEGIN{printf "%.1f",t/c}')

    echo ""
    echo "  ┌──────────────── 適用プレビュー ─────────────────┐"
    printf "  │  CR_BW = %-6s  AF41 SP保証上限 = %-7s       │\n" \
        "$(to_disp $cr_m)" "$(to_disp $(( cr_m * 4 / 7 )))"
    echo "  │                                                   │"
    printf "  │  TX1 AF41(SP) : %-5s/stream × 4 = %-10s  │\n" \
        "$(to_disp $tx1_m)" "$(to_disp $(( tx1_m * 4 )))"
    printf "  │  TX2 AF42(WRR): %-5s/stream × 4 = %-10s  │\n" \
        "$(to_disp $tx2_m)" "$(to_disp $(( tx2_m * 4 )))"
    printf "  │  TX3 AF43(WRR): %-5s/stream × 4 = %-10s  │\n" \
        "$(to_disp $tx3_m)" "$(to_disp $(( tx3_m * 4 )))"
    printf "  │  総送信量: %-7s (CR_BW の %sx)            │\n" \
        "$(to_disp $total)" "$ratio"
    echo "  ├──────────────── 期待スループット ───────────────┤"
    printf "  │  AF41 (SP) : %-8s  損失 %2d%%                │\n" \
        "$(to_disp $r1)" $l1
    printf "  │  AF42 (WRR): %-8s  損失 %2d%%                │\n" \
        "$(to_disp $r2)" $l2
    printf "  │  AF43 (WRR): %-8s  損失 %2d%%                │\n" \
        "$(to_disp $r3)" $l3
    echo "  └───────────────────────────────────────────────────┘"
}

# ── TC/HTB を即時再適用 ───────────────────────────────────────────────
try_apply() {
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^LER_Ingress$'; then
        echo "  frr_dscp_te.sh を適用中..."
        bash "$SCRIPT_DIR/frr_dscp_te.sh" > /dev/null
        echo "  [ok] TC/HTB 再適用完了"
    else
        echo "  (コンテナ未起動 — 次回 frr_all_up.sh 実行時に反映されます)"
    fi
}

# ════════════════════════════════════════════════════════════════
# メインループ
# ════════════════════════════════════════════════════════════════
while true; do
    # ループ先頭で最新値を再読み込み（apply後に値が変わるため）
    # shellcheck source=./lab_config.sh
    source "$CONFIG_FILE"

    clear
    echo "════════════════════════════════════════════════════"
    echo "   TX 送信レート設定メニュー"
    echo "════════════════════════════════════════════════════"
    echo ""

    # 現在値の表示
    local_cr_m=$(rate_to_mbps "$CR1_BW")
    local_t1_m=$(rate_to_mbps "$TX1_RATE")
    local_t2_m=$(rate_to_mbps "$TX2_RATE")
    local_t3_m=$(rate_to_mbps "$TX3_RATE")
    read -r r1 r2 r3 l1 l2 l3 <<< "$(calc_expected "$local_cr_m" "$local_t1_m" "$local_t2_m" "$local_t3_m")"
    total=$(( (local_t1_m + local_t2_m + local_t3_m) * 4 ))
    ratio=$(awk -v t=$total -v c=$local_cr_m 'BEGIN{printf "%.1f",t/c}')

    printf "  現在の設定  CR=%-6s  総送信 %-7s [%sx 超過]\n" \
        "$(to_disp $local_cr_m)" "$(to_disp $total)" "$ratio"
    printf "  AF41(SP)  TX1=%-6s  受信期待 %-7s  損失 %2d%%\n" \
        "$TX1_RATE" "$(to_disp $r1)" $l1
    printf "  AF42(WRR) TX2=%-6s  受信期待 %-7s  損失 %2d%%\n" \
        "$TX2_RATE" "$(to_disp $r2)" $l2
    printf "  AF43(WRR) TX3=%-6s  受信期待 %-7s  損失 %2d%%\n" \
        "$TX3_RATE" "$(to_disp $r3)" $l3
    echo ""
    echo "  ──────────────────────────────────────────────────"
    echo "  プリセット"
    echo "  ──────────────────────────────────────────────────"
    for i in $(seq 1 $PRESET_COUNT); do
        print_preset "$i" "$CR1_BW" "$TX1_RATE" "$TX2_RATE" "$TX3_RATE"
    done
    echo "  c) カスタム入力"
    echo "  q) 終了"
    echo "  ──────────────────────────────────────────────────"
    printf "  選択 [1-%d/c/q]: " $PRESET_COUNT
    read -r choice

    case "$choice" in
        [1-9])
            idx=$(( choice - 1 ))
            if [ "$idx" -ge 0 ] && [ "$idx" -lt "$PRESET_COUNT" ]; then
                NEW_CR="${PCR[$idx]}"
                NEW_TX1="${PTX1[$idx]}"
                NEW_TX2="${PTX2[$idx]}"
                NEW_TX3="${PTX3[$idx]}"
            else
                echo "  [!] 無効な選択"; sleep 1; continue
            fi
            ;;
        c|C)
            custom_input "$CR1_BW" "$TX1_RATE" "$TX2_RATE" "$TX3_RATE"
            ;;
        q|Q)
            echo "  終了（変更なし）"
            exit 0
            ;;
        "")
            continue
            ;;
        *)
            echo "  [!] 無効な選択"; sleep 1; continue
            ;;
    esac

    show_preview

    echo ""
    printf "  lab_config.sh に保存しますか? [y/N]: "
    read -r confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        update_config "$NEW_TX1" "$NEW_TX2" "$NEW_TX3" "$NEW_CR"
        echo "  [ok] lab_config.sh を更新しました"
        try_apply
        echo ""
        printf "  メニューに戻りますか? [Y/n]: "
        read -r cont
        [[ "$cont" =~ ^[Nn]$ ]] && { echo "  終了"; exit 0; }
    fi
done
