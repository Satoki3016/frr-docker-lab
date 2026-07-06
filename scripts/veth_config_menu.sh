#!/bin/bash
# veth_config_menu.sh
# lab_config_veth.sh の設定をインタラクティブに変更するメニュー
#
# 使い方:
#   bash scripts/veth_config_menu.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="${SCRIPT_DIR}/lab_config_veth.sh"

# 設定ファイルから現在値を読み取る
get_val() {
    grep -E "^${1}=" "$CONFIG" | sed 's/.*:-\([^}]*\)}.*/\1/' | tr -d '"'
}

# 設定ファイルの値を書き換える
set_val() {
    local key=$1 val=$2
    sed -i "s|${key}=\"\${${key}:-[^}]*}\"|${key}=\"\${${key}:-${val}}\"|" "$CONFIG"
}

show_menu() {
    clear
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  veth 実験 設定変更メニュー"
    echo "  設定ファイル: scripts/lab_config_veth.sh"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "  【送信レート（iperf3 -b 値、4ストリーム × レート）】"
    echo "   1. TX1_RATE  AF41（高優先）  現在: $(get_val TX1_RATE)"
    echo "   2. TX2_RATE  AF42（中優先）  現在: $(get_val TX2_RATE)"
    echo "   3. TX3_RATE  AF43（低優先）  現在: $(get_val TX3_RATE)"
    echo ""
    echo "  【CRリンク帯域（HTB root rate）】"
    echo "   4. CR1_BW                    現在: $(get_val CR1_BW)"
    echo "   5. CR2_BW                    現在: $(get_val CR2_BW)"
    echo "   6. CR3_BW                    現在: $(get_val CR3_BW)"
    echo ""
    echo "  【CRリンク遅延（netem delay）】"
    echo "   7. CR1_DELAY                 現在: $(get_val CR1_DELAY)"
    echo "   8. CR2_DELAY                 現在: $(get_val CR2_DELAY)"
    echo "   9. CR3_DELAY                 現在: $(get_val CR3_DELAY)"
    echo ""
    echo "  【WRR 比率（quantum = 値 × 9000 bytes）】"
    echo "  10. WRR_HI   AF41（SP/高）    現在: $(get_val WRR_HI)"
    echo "  11. WRR_ME   AF42（中）       現在: $(get_val WRR_ME)"
    echo "  12. WRR_LO   AF43（低）       現在: $(get_val WRR_LO)"
    echo ""
    echo "  【一括変更】"
    echo "   a. TX1/TX2/TX3 を同じ値に一括変更"
    echo "   b. CR1/CR2/CR3 帯域を同じ値に一括変更"
    echo ""
    echo "  【実験実行】"
    echo "   r. QoS再適用 → 実験開始"
    echo ""
    echo "   q. 終了"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

change_val() {
    local key=$1 label=$2 unit=$3
    local cur; cur=$(get_val "$key")
    echo ""
    echo "  ${label}（現在: ${cur}）"
    printf "  新しい値を入力 [${unit}]: "
    read -r newval
    if [ -z "$newval" ]; then
        echo "  → 変更なし"
        return
    fi
    set_val "$key" "$newval"
    echo "  → ${key} を ${cur} から ${newval} に変更しました"
}

while true; do
    show_menu
    printf "  番号を選択: "
    read -r choice
    case "$choice" in
        1)  change_val TX1_RATE  "AF41 送信レート" "例: 3G, 5G, 10G, 15G" ;;
        2)  change_val TX2_RATE  "AF42 送信レート" "例: 5G, 10G, 15G" ;;
        3)  change_val TX3_RATE  "AF43 送信レート" "例: 5G, 10G, 15G" ;;
        4)  change_val CR1_BW    "CR1 リンク帯域"  "例: 10G, 25G, 40G" ;;
        5)  change_val CR2_BW    "CR2 リンク帯域"  "例: 10G, 25G, 40G" ;;
        6)  change_val CR3_BW    "CR3 リンク帯域"  "例: 10G, 25G, 40G" ;;
        7)  change_val CR1_DELAY "CR1 遅延"        "例: 0ms, 10ms, 50ms" ;;
        8)  change_val CR2_DELAY "CR2 遅延"        "例: 0ms, 10ms, 50ms" ;;
        9)  change_val CR3_DELAY "CR3 遅延"        "例: 0ms, 10ms, 50ms" ;;
        10) change_val WRR_HI    "WRR_HI AF41比率" "例: 4 (quantum=36000B)" ;;
        11) change_val WRR_ME    "WRR_ME AF42比率" "例: 2 (quantum=18000B)" ;;
        12) change_val WRR_LO    "WRR_LO AF43比率" "例: 1 (quantum=9000B)" ;;
        a|A)
            printf "  TX1/TX2/TX3 を同じ値に変更 [例: 3G, 5G, 10G]: "
            read -r newval
            if [ -n "$newval" ]; then
                set_val TX1_RATE "$newval"
                set_val TX2_RATE "$newval"
                set_val TX3_RATE "$newval"
                echo "  → TX1/TX2/TX3 をすべて ${newval} に変更しました"
                echo "  → 合計送信量: 4×${newval}×3クラス"
            fi ;;
        b|B)
            printf "  CR1/CR2/CR3 帯域を同じ値に変更 [例: 10G, 25G, 40G]: "
            read -r newval
            if [ -n "$newval" ]; then
                set_val CR1_BW "$newval"
                set_val CR2_BW "$newval"
                set_val CR3_BW "$newval"
                echo "  → CR1/CR2/CR3 をすべて ${newval} に変更しました"
            fi ;;
        r|R)
            echo ""
            printf "  計測時間（秒）[デフォルト: 60]: "
            read -r duration
            duration="${duration:-60}"
            echo ""
            echo "  シナリオを選択:"
            echo "   1) normal"
            echo "   2) failure"
            echo "   3) failure_reroute"
            echo "   4) 全シナリオ (normal → failure → failure_reroute)"
            printf "  選択 [1-4]: "
            read -r schoice
            case "$schoice" in
                1) scenarios=(normal) ;;
                2) scenarios=(failure) ;;
                3) scenarios=(failure_reroute) ;;
                4) scenarios=(normal failure failure_reroute) ;;
                *) echo "  無効な選択です"; continue ;;
            esac
            echo ""
            echo "  === QoS 設定を再適用中 ==="
            sudo bash "${SCRIPT_DIR}/frr_dscp_te.sh"
            echo ""
            for sc in "${scenarios[@]}"; do
                echo "  === 実験開始: ${sc} (${duration}s) ==="
                sudo bash "${SCRIPT_DIR}/frr_measure.sh" "$duration" "$sc"
                echo ""
            done
            echo "  === 実験完了 ==="
            printf "  Enterで続ける..."
            read -r ;;
        q|Q) echo ""; echo "  終了します。"; break ;;
        *) echo "  無効な選択です" ;;
    esac
    echo ""
    printf "  Enterで続ける..."
    read -r
done
