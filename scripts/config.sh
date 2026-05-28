#!/bin/bash
# 設定変更ツール（対話式）
#
# 使い方:
#   sudo bash scripts/config.sh          # 対話式メニュー
#   sudo bash scripts/config.sh show     # 現在の設定を表示
#
# 一括変更（非対話式）:
#   sudo bash scripts/config.sh set CR1_BW=20mbit CR2_BW=10mbit TX1_RATE=5M

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/lab_config.sh"

source "$CONFIG_FILE"

# デフォルト (lab_config.sh がまだ持っていない場合のフォールバック)
WRR_HI="${WRR_HI:-4}"
WRR_ME="${WRR_ME:-2}"
WRR_LO="${WRR_LO:-1}"
DELAY_ME="${DELAY_ME:-10ms}"
DELAY_LO="${DELAY_LO:-40ms}"
NETEM_LIMIT="${NETEM_LIMIT:-150}"

# ----------------------------------------------------------------
# 設定を保存
# ----------------------------------------------------------------
save_config() {
    cat > "$CONFIG_FILE" << EOF
#!/bin/bash
# ラボ設定ファイル

TX1_RATE="\${TX1_RATE:-${TX1_RATE}}"
TX2_RATE="\${TX2_RATE:-${TX2_RATE}}"
TX3_RATE="\${TX3_RATE:-${TX3_RATE}}"

CR1_BW="\${CR1_BW:-${CR1_BW}}"
CR2_BW="\${CR2_BW:-${CR2_BW}}"
CR3_BW="\${CR3_BW:-${CR3_BW}}"

CR1_DELAY="\${CR1_DELAY:-${CR1_DELAY}}"
CR2_DELAY="\${CR2_DELAY:-${CR2_DELAY}}"
CR3_DELAY="\${CR3_DELAY:-${CR3_DELAY}}"

# クラス別追加遅延 (LER_Ingress egress の HTB リーフで付与)
# ECMP ハッシュに依存せず AF41 < AF42 < AF43 の遅延順序を保証する
DELAY_ME="\${DELAY_ME:-${DELAY_ME}}"   # AF42 中優先クラスへの追加遅延
DELAY_LO="\${DELAY_LO:-${DELAY_LO}}"   # AF43 低優先クラスへの追加遅延

# WRR 重み比率 (AF41:AF42:AF43)
WRR_HI="\${WRR_HI:-${WRR_HI}}"   # AF41 高優先の重み
WRR_ME="\${WRR_ME:-${WRR_ME}}"   # AF42 中優先の重み
WRR_LO="\${WRR_LO:-${WRR_LO}}"   # AF43 低優先の重み

# netem キュー長 (パケット数) — 最大キュー遅延を制御
# RTT_max ≈ DELAY_LO + NETEM_LIMIT × 1400B / (CR_BW × WRR_LO/WRR_sum / 8) × 2ホップ
# 例: limit=150, CR_BW=100M, WRR=4:2:1 → 117ms/hop × 2 + 40ms(DELAY_LO) ≈ 275ms
NETEM_LIMIT="\${NETEM_LIMIT:-${NETEM_LIMIT}}"
EOF
}

# ----------------------------------------------------------------
# 設定を表示
# ----------------------------------------------------------------
show_config() {
    echo ""
    echo "┌─────────────────────────────────────────────────────────────────┐"
    echo "│                        現在の設定                               │"
    echo "├──────────┬──────────┬──────────┬───────────────────────────────┤"
    echo "│          │  帯域幅  │  遅延    │  送信レート                   │"
    echo "├──────────┼──────────┼──────────┼───────────────────────────────┤"
    printf "│ CR1      │ %-8s │ %-8s │ TX1: %-24s│\n" "$CR1_BW" "$CR1_DELAY" "$TX1_RATE"
    printf "│ CR2      │ %-8s │ %-8s │ TX2: %-24s│\n" "$CR2_BW" "$CR2_DELAY" "$TX2_RATE"
    printf "│ CR3      │ %-8s │ %-8s │ TX3: %-24s│\n" "$CR3_BW" "$CR3_DELAY" "$TX3_RATE"
    echo "├──────────┴──────────┴──────────┴───────────────────────────────┤"
    printf "│ WRR 比率  AF41:AF42:AF43 = %d:%d:%d                               │\n" "$WRR_HI" "$WRR_ME" "$WRR_LO"
    printf "│ クラス遅延 AF42 追加: %-8s  AF43 追加: %-8s            │\n" "$DELAY_ME" "$DELAY_LO"
    printf "│ netem キュー長: %-4s pkt  (最大RTT目安: %dms)                   │\n" \
        "$NETEM_LIMIT" \
        "$(( NETEM_LIMIT * 1400 * 8 * 2 / 100000 + ${DELAY_LO%ms} + 50 ))"
    echo "└─────────────────────────────────────────────────────────────────┘"
    echo ""
}

# ----------------------------------------------------------------
# 即時適用（コンテナ起動中のみ）
# ----------------------------------------------------------------
apply_now() {
    if ip netns list 2>/dev/null | awk '{print $1}' | grep -qxF "LER_Ingress_ns"; then
        echo "→ TC 設定を適用中 (virttrx_tc.sh)..."
        bash "$SCRIPT_DIR/virttrx_tc.sh"
        echo "→ 適用完了"
    elif ip netns list 2>/dev/null | awk '{print $1}' | grep -qxF "LER_Ingress"; then
        echo "→ TC 設定を適用中 (30_tc.sh)..."
        bash "$SCRIPT_DIR/30_tc.sh"
        echo "→ 適用完了"
    else
        echo "→ namespace 未起動のため次回セットアップ時に反映されます"
    fi
}

# ----------------------------------------------------------------
# 入力補助: 現在値をデフォルトにした read
# ----------------------------------------------------------------
ask() {
    local label=$1 current=$2 varname=$3
    printf "  %-20s [現在: %-8s] → " "$label" "$current"
    read -r input
    if [ -n "$input" ]; then
        eval "$varname='$input'"
    fi
}

# ================================================================
# メイン処理
# ================================================================

# --- show モード ---
if [ "$1" = "show" ]; then
    show_config
    exit 0
fi

# --- 非対話式 set モード ---
if [ "$1" = "set" ]; then
    shift
    for arg in "$@"; do
        key="${arg%%=*}"
        val="${arg#*=}"
        case "$key" in
            TX1_RATE) TX1_RATE="$val" ;;
            TX2_RATE) TX2_RATE="$val" ;;
            TX3_RATE) TX3_RATE="$val" ;;
            CR1_BW)   CR1_BW="$val"   ;;
            CR2_BW)   CR2_BW="$val"   ;;
            CR3_BW)   CR3_BW="$val"   ;;
            CR1_DELAY) CR1_DELAY="$val" ;;
            CR2_DELAY) CR2_DELAY="$val" ;;
            CR3_DELAY) CR3_DELAY="$val" ;;
            DELAY_ME)    DELAY_ME="$val"    ;;
            DELAY_LO)    DELAY_LO="$val"    ;;
            WRR_HI)      WRR_HI="$val"      ;;
            WRR_ME)      WRR_ME="$val"      ;;
            WRR_LO)      WRR_LO="$val"      ;;
            NETEM_LIMIT) NETEM_LIMIT="$val" ;;
            *) echo "[ERROR] 不明なキー: $key" >&2; exit 1 ;;
        esac
    done
    save_config
    show_config
    apply_now
    exit 0
fi

# --- 対話式メニュー ---
show_config

echo "変更したい項目を選んでください:"
echo "  1) 送信レート (TX1/TX2/TX3)"
echo "  2) リンク帯域幅 (CR1/CR2/CR3)"
echo "  3) リンク遅延 (CR1/CR2/CR3)"
echo "  4) WRR 比率 (AF41:AF42:AF43)"
echo "  5) クラス別追加遅延 (DELAY_ME/DELAY_LO)"
echo "  6) すべて変更"
echo "  q) キャンセル"
echo ""
printf "選択 [1-6/q]: "
read -r choice

case "$choice" in
    1)
        echo ""
        echo "--- 送信レート ---"
        echo "  例: 500M, 11.2M, 5M, 1M"
        ask "TX1 (AF41 High)" "$TX1_RATE" TX1_RATE
        ask "TX2 (AF42 Medium)" "$TX2_RATE" TX2_RATE
        ask "TX3 (AF43 Low)" "$TX3_RATE" TX3_RATE
        ;;
    2)
        echo ""
        echo "--- リンク帯域幅 ---"
        echo "  例: 10mbit, 5mbit, 1mbit, 100mbit"
        ask "CR1_BW" "$CR1_BW" CR1_BW
        ask "CR2_BW" "$CR2_BW" CR2_BW
        ask "CR3_BW" "$CR3_BW" CR3_BW
        ;;
    3)
        echo ""
        echo "--- リンク遅延 ---"
        echo "  例: 2ms, 5ms, 10ms, 50ms"
        ask "CR1_DELAY" "$CR1_DELAY" CR1_DELAY
        ask "CR2_DELAY" "$CR2_DELAY" CR2_DELAY
        ask "CR3_DELAY" "$CR3_DELAY" CR3_DELAY
        ;;
    4)
        echo ""
        echo "--- WRR 比率 (整数値) ---"
        echo "  例: 4:2:1 → HI=4 ME=2 LO=1"
        ask "WRR_HI (AF41)" "$WRR_HI" WRR_HI
        ask "WRR_ME (AF42)" "$WRR_ME" WRR_ME
        ask "WRR_LO (AF43)" "$WRR_LO" WRR_LO
        ;;
    5)
        echo ""
        echo "--- クラス別追加遅延 / キュー長 ---"
        echo "  DELAY 例: 10ms, 40ms, 0ms"
        echo "  NETEM_LIMIT 例: 50, 100, 150, 200  (小さいほど最大遅延が低下)"
        ask "DELAY_ME (AF42 追加)" "$DELAY_ME" DELAY_ME
        ask "DELAY_LO (AF43 追加)" "$DELAY_LO" DELAY_LO
        ask "NETEM_LIMIT (pkt)" "$NETEM_LIMIT" NETEM_LIMIT
        ;;
    6)
        echo ""
        echo "--- 送信レート (Enter でスキップ) ---"
        ask "TX1 (AF41 High)" "$TX1_RATE" TX1_RATE
        ask "TX2 (AF42 Medium)" "$TX2_RATE" TX2_RATE
        ask "TX3 (AF43 Low)" "$TX3_RATE" TX3_RATE
        echo ""
        echo "--- リンク帯域幅 (Enter でスキップ) ---"
        ask "CR1_BW" "$CR1_BW" CR1_BW
        ask "CR2_BW" "$CR2_BW" CR2_BW
        ask "CR3_BW" "$CR3_BW" CR3_BW
        echo ""
        echo "--- リンク遅延 (Enter でスキップ) ---"
        ask "CR1_DELAY" "$CR1_DELAY" CR1_DELAY
        ask "CR2_DELAY" "$CR2_DELAY" CR2_DELAY
        ask "CR3_DELAY" "$CR3_DELAY" CR3_DELAY
        echo ""
        echo "--- WRR 比率 (Enter でスキップ) ---"
        ask "WRR_HI (AF41)" "$WRR_HI" WRR_HI
        ask "WRR_ME (AF42)" "$WRR_ME" WRR_ME
        ask "WRR_LO (AF43)" "$WRR_LO" WRR_LO
        echo ""
        echo "--- クラス別追加遅延 / キュー長 (Enter でスキップ) ---"
        ask "DELAY_ME (AF42 追加)" "$DELAY_ME" DELAY_ME
        ask "DELAY_LO (AF43 追加)" "$DELAY_LO" DELAY_LO
        ask "NETEM_LIMIT (pkt)" "$NETEM_LIMIT" NETEM_LIMIT
        ;;
    q|Q|"")
        echo "キャンセルしました"
        exit 0
        ;;
    *)
        echo "[ERROR] 無効な選択です"
        exit 1
        ;;
esac

echo ""
save_config
show_config

printf "コンテナに即時適用しますか？ [y/N]: "
read -r yn
if [ "$yn" = "y" ] || [ "$yn" = "Y" ]; then
    apply_now
fi
