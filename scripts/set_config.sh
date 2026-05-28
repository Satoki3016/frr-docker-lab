#!/bin/bash
# パラメータ設定スクリプト
#
# 使い方:
#   bash scripts/set_config.sh [オプション]
#
# オプション:
#   --cr1-bw   <rate>    CR1 リンク帯域幅 (例: 10mbit, 20mbit)
#   --cr2-bw   <rate>    CR2 リンク帯域幅 (例: 5mbit)
#   --cr3-bw   <rate>    CR3 リンク帯域幅 (例: 1mbit, 2mbit)
#   --cr1-delay <time>   CR1 リンク遅延   (例: 2ms, 10ms)
#   --cr2-delay <time>   CR2 リンク遅延
#   --cr3-delay <time>   CR3 リンク遅延
#   --tx1-rate <rate>    Tx1 送信レート   (例: 11.2M, 5M)
#   --tx2-rate <rate>    Tx2 送信レート
#   --tx3-rate <rate>    Tx3 送信レート
#   --apply              変更後に tc を即時適用 (コンテナ起動中のみ)
#   --show               現在の設定を表示して終了
#
# 例:
#   bash scripts/set_config.sh --show
#   bash scripts/set_config.sh --cr1-bw 20mbit --cr2-bw 10mbit --apply
#   bash scripts/set_config.sh --tx1-rate 5M --tx2-rate 5M --tx3-rate 5M
#   bash scripts/set_config.sh --cr3-bw 2mbit --cr3-delay 5ms --apply

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/lab_config.sh"

# ----------------------------------------------------------------
# 現在の設定を読み込む
# ----------------------------------------------------------------
source "$CONFIG_FILE"

# ----------------------------------------------------------------
# 引数パース
# ----------------------------------------------------------------
DO_APPLY=0
DO_SHOW=0

while [ $# -gt 0 ]; do
    case "$1" in
        --cr1-bw)    CR1_BW="$2";    shift 2 ;;
        --cr2-bw)    CR2_BW="$2";    shift 2 ;;
        --cr3-bw)    CR3_BW="$2";    shift 2 ;;
        --cr1-delay) CR1_DELAY="$2"; shift 2 ;;
        --cr2-delay) CR2_DELAY="$2"; shift 2 ;;
        --cr3-delay) CR3_DELAY="$2"; shift 2 ;;
        --tx1-rate)  TX1_RATE="$2";  shift 2 ;;
        --tx2-rate)  TX2_RATE="$2";  shift 2 ;;
        --tx3-rate)  TX3_RATE="$2";  shift 2 ;;
        --apply)     DO_APPLY=1;     shift ;;
        --show)      DO_SHOW=1;      shift ;;
        -h|--help)
            sed -n '2,20p' "$0" | grep '^#' | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "[ERROR] 不明なオプション: $1" >&2
            exit 1
            ;;
    esac
done

# ----------------------------------------------------------------
# 現在の設定を表示して終了 (--show)
# ----------------------------------------------------------------
show_config() {
    echo "=== 現在の設定 ==="
    printf "  %-15s %-10s %-10s\n" "パラメータ" "値" "説明"
    printf "  %-15s %-10s %-10s\n" "----------" "--" "----"
    printf "  %-15s %-10s %s\n" "CR1_BW"    "$CR1_BW"    "(CR1 リンク帯域幅)"
    printf "  %-15s %-10s %s\n" "CR2_BW"    "$CR2_BW"    "(CR2 リンク帯域幅)"
    printf "  %-15s %-10s %s\n" "CR3_BW"    "$CR3_BW"    "(CR3 リンク帯域幅)"
    printf "  %-15s %-10s %s\n" "CR1_DELAY" "$CR1_DELAY" "(CR1 リンク遅延)"
    printf "  %-15s %-10s %s\n" "CR2_DELAY" "$CR2_DELAY" "(CR2 リンク遅延)"
    printf "  %-15s %-10s %s\n" "CR3_DELAY" "$CR3_DELAY" "(CR3 リンク遅延)"
    printf "  %-15s %-10s %s\n" "TX1_RATE"  "$TX1_RATE"  "(Tx1 送信レート)"
    printf "  %-15s %-10s %s\n" "TX2_RATE"  "$TX2_RATE"  "(Tx2 送信レート)"
    printf "  %-15s %-10s %s\n" "TX3_RATE"  "$TX3_RATE"  "(Tx3 送信レート)"
}

if [ "$DO_SHOW" -eq 1 ]; then
    show_config
    exit 0
fi

# ----------------------------------------------------------------
# 引数なしなら設定を表示してヘルプを案内
# ----------------------------------------------------------------
if [ $# -eq 0 ] && [ "$DO_APPLY" -eq 0 ]; then
    show_config
    echo ""
    echo "変更するには --cr1-bw, --tx1-rate などのオプションを指定してください。"
    echo "例: bash scripts/set_config.sh --cr1-bw 20mbit --apply"
    exit 0
fi

# ----------------------------------------------------------------
# lab_config.sh を新しい値で上書き
# ----------------------------------------------------------------
cat > "$CONFIG_FILE" << EOF
#!/bin/bash
# ラボ設定ファイル
# ここを編集するか、環境変数で上書きすることで各パラメータを変更できます
# 例: CR1_BW=20mbit bash scripts/30_tc.sh

# ----------------------------------------------------------------
# トラフィック送信レート (各 Tx → Rx への UDP 送信帯域)
# 形式: "11.2M", "5M", "500K" など (iperf3 -b オプションの値)
# ----------------------------------------------------------------
TX1_RATE="\${TX1_RATE:-${TX1_RATE}}"   # Tx1 → Rx1 (AF41 High)
TX2_RATE="\${TX2_RATE:-${TX2_RATE}}"   # Tx2 → Rx2 (AF42 Medium)
TX3_RATE="\${TX3_RATE:-${TX3_RATE}}"   # Tx3 → Rx3 (AF43 Low)

# ----------------------------------------------------------------
# リンク帯域幅 (LER_Ingress ↔ CR* 間 / CR* ↔ LER_Egress 間の上限)
# 形式: "10mbit", "5mbit", "500kbit" など (tc rate オプションの値)
# ----------------------------------------------------------------
CR1_BW="\${CR1_BW:-${CR1_BW}}"   # CR1 経由リンク (AF41 Primary)
CR2_BW="\${CR2_BW:-${CR2_BW}}"    # CR2 経由リンク (AF42 Primary)
CR3_BW="\${CR3_BW:-${CR3_BW}}"    # CR3 経由リンク (AF43 Primary)

# ----------------------------------------------------------------
# リンク遅延 (片道, LER_Ingress 送出 と CR 送出 の両方に適用)
# 実際の RTT ≒ 設定値 × 2 (往復)
# 形式: "2ms", "10ms", "100ms" など (tc netem delay の値)
# ----------------------------------------------------------------
CR1_DELAY="\${CR1_DELAY:-${CR1_DELAY}}"    # CR1 経由リンク
CR2_DELAY="\${CR2_DELAY:-${CR2_DELAY}}"    # CR2 経由リンク
CR3_DELAY="\${CR3_DELAY:-${CR3_DELAY}}"   # CR3 経由リンク
EOF

echo "=== lab_config.sh を更新しました ==="
show_config

# ----------------------------------------------------------------
# --apply: 起動中のコンテナに即時適用
# ----------------------------------------------------------------
if [ "$DO_APPLY" -eq 1 ]; then
    echo ""
    if ip netns list 2>/dev/null | awk '{print $1}' | grep -qxF "LER_Ingress_ns"; then
        echo "=== TC 設定を即時適用中 (virttrx_tc.sh) ==="
        bash "$SCRIPT_DIR/virttrx_tc.sh"
        echo "適用完了"
    elif ip netns list 2>/dev/null | awk '{print $1}' | grep -qxF "LER_Ingress"; then
        echo "=== TC 設定を即時適用中 (30_tc.sh) ==="
        bash "$SCRIPT_DIR/30_tc.sh"
        echo "適用完了"
    else
        echo "[WARN] namespace が起動していません。次回セットアップ時に反映されます。"
    fi
fi
