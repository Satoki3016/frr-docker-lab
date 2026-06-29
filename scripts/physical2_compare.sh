#!/bin/bash
# 物理Docker環境 フェイルオーバー比較計測
# measure.sh の failure / failure_rsvp / normal に対応する物理実験
#
# シナリオ:
#   normal       : 障害なし 60秒計測
#   failure      : t=20s に leri-cr1 netem loss 100% (operstate=UP, OSPFは反応しない)
#                  → measure.sh failure と同等 (静的ECMPのまま 1/3 がブラックホール)
#   failure_ospf : t=20s に leri-cr1 ip link down (OSPF+BFD が検知・迂回)
#                  → measure.sh failure_rsvp より高速な動的フェイルオーバー
#
# 使い方:
#   sudo bash scripts/physical2_compare.sh [duration] [normal|failure|failure_ospf]
# 例:
#   sudo bash scripts/physical2_compare.sh 60 normal
#   sudo bash scripts/physical2_compare.sh 60 failure
#   sudo bash scripts/physical2_compare.sh 60 failure_ospf

set -e

DURATION=${1:-60}
SCENARIO=${2:-normal}
PING_INTERVAL=0.1      # 100ms
PING_TARGET="10.20.1.2"
PING_SRC="Tx1"
SEP="═══════════════════════════════════════════════════"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB_DIR="$(dirname "$SCRIPT_DIR")"
RESULTS_DIR="$LAB_DIR/results_physical/${SCENARIO}"
mkdir -p "$RESULTS_DIR"

if ! [[ "$SCENARIO" =~ ^(normal|failure|failure_ospf)$ ]]; then
    echo "[ERROR] シナリオは normal / failure / failure_ospf のいずれかを指定"
    exit 1
fi

echo "$SEP"
echo "■ 物理Docker フェイルオーバー比較計測"
echo "  シナリオ : $SCENARIO"
echo "  計測時間 : ${DURATION}秒"
echo "  結果保存 : $RESULTS_DIR"
echo "$SEP"

# ── 初期状態確認 ─────────────────────────────────────────────────
echo ""
echo "【初期状態】"
echo "--- OSPF neighbors (LER_Ingress) ---"
docker exec frr-LER_Ingress vtysh -c "show ip ospf neighbor" 2>/dev/null | \
    grep -v "^$\|Neighbor" | sed 's/^/  /' || true

echo ""
echo "--- IPルート (10.20.1.x) ---"
docker exec LER_Ingress ip route show | grep "10.20.1" | sed 's/^/  /' || true

echo ""
echo "--- Tx1 → Rx1 traceroute (初期経路) ---"
docker exec "$PING_SRC" traceroute -n -w 1 -q 1 "$PING_TARGET" 2>/dev/null | sed 's/^/  /' || true

# ── failure 用: netem 復旧関数 ───────────────────────────────────
restore_netem() {
    docker exec LER_Ingress tc qdisc change dev leri-cr1 \
        root netem delay 0ms loss 0% 2>/dev/null || \
    docker exec LER_Ingress tc qdisc del dev leri-cr1 root 2>/dev/null || true
}

# ── ping 計測開始 ─────────────────────────────────────────────────
echo ""
echo "$SEP"
PING_LOG="$RESULTS_DIR/ping.log"
PING_TS_LOG="$RESULTS_DIR/ping_ts.log"

echo "【計測開始】 ping ${PING_INTERVAL}s 間隔 × ${DURATION}秒"
docker exec "$PING_SRC" ping -i "$PING_INTERVAL" -W 1 -c $((DURATION * 10 + 10)) \
    "$PING_TARGET" 2>/dev/null | \
    while IFS= read -r line; do
        printf "%s %s\n" "$(date +%T.%3N)" "$line"
    done > "$PING_TS_LOG" &
PING_PID=$!

sleep 1  # ping 安定まで待機

# ── 障害注入 ─────────────────────────────────────────────────────
FAILURE_PID=""
T_DOWN=""
T_UP=""

if [ "$SCENARIO" = "failure" ]; then
    echo ""
    echo "  t=20s: leri-cr1 netem loss 100% (operstate=UP のまま、OSPF 反応なし)"
    echo "  t=40s: 復旧"
    (
        sleep 19
        echo ""
        T_DOWN_MS=$(date +%s%3N)
        T_DOWN_STR=$(date +%T.%3N)
        echo "  [$T_DOWN_STR] leri-cr1 netem loss 100% → ブラックホール開始"
        # netem が未設定の場合は add、設定済みなら change
        docker exec LER_Ingress tc qdisc add dev leri-cr1 root netem loss 100% 2>/dev/null || \
        docker exec LER_Ingress tc qdisc change dev leri-cr1 root netem loss 100%
        echo "$T_DOWN_MS" > /tmp/compare_t_down

        sleep 20
        T_UP_MS=$(date +%s%3N)
        T_UP_STR=$(date +%T.%3N)
        echo "  [$T_UP_STR] leri-cr1 復旧 (netem リセット)"
        restore_netem
        echo "$T_UP_MS" > /tmp/compare_t_up
    ) &
    FAILURE_PID=$!

elif [ "$SCENARIO" = "failure_ospf" ]; then
    echo ""
    echo "  t=20s: leri-cr1 ip link down → OSPF+BFD 検知 → 迂回"
    echo "  t=40s: 復旧"
    (
        sleep 19
        echo ""
        T_DOWN_MS=$(date +%s%3N)
        T_DOWN_STR=$(date +%T.%3N)
        echo "  [$T_DOWN_STR] leri-cr1 DOWN ↓"
        docker exec LER_Ingress ip link set leri-cr1 down
        echo "$T_DOWN_MS" > /tmp/compare_t_down

        sleep 20
        T_UP_MS=$(date +%s%3N)
        T_UP_STR=$(date +%T.%3N)
        echo "  [$T_UP_STR] leri-cr1 UP ↑"
        docker exec LER_Ingress ip link set leri-cr1 up
        echo "$T_UP_MS" > /tmp/compare_t_up
    ) &
    FAILURE_PID=$!
fi

# ── 計測時間待機 ─────────────────────────────────────────────────
echo ""
echo "計測中... ${DURATION}秒待機"
sleep "$DURATION"

# ── 終了処理 ─────────────────────────────────────────────────────
kill "$PING_PID" 2>/dev/null || true
[ -n "$FAILURE_PID" ] && wait "$FAILURE_PID" 2>/dev/null || true

# 確実に復旧
if [ "$SCENARIO" = "failure" ]; then
    restore_netem
elif [ "$SCENARIO" = "failure_ospf" ]; then
    docker exec LER_Ingress ip link set leri-cr1 up 2>/dev/null || true
fi

sleep 0.5

# ── 結果集計 ─────────────────────────────────────────────────────
echo ""
echo "$SEP"
echo "【結果集計】"

# ping ログからタイムスタンプ付きに変換（既にts付き）
cp "$PING_TS_LOG" "$PING_LOG"

TOTAL=$(grep -c "bytes from\|Request timeout\|Unreachable" "$PING_TS_LOG" 2>/dev/null || echo 0)
LOSS=$(grep -c "Request timeout\|Unreachable\|100% packet loss" "$PING_TS_LOG" 2>/dev/null || echo 0)
OK=$((TOTAL - LOSS))

echo "  総パケット数 : $TOTAL"
echo "  到達         : $OK"
echo "  ロスト       : $LOSS"

if [ "$TOTAL" -gt 0 ] && [ "$LOSS" -gt 0 ]; then
    LOSS_RATE=$(echo "scale=2; $LOSS * 100 / $TOTAL" | bc 2>/dev/null || echo "?")
    echo "  ロス率       : ${LOSS_RATE}%"
    RECOVERY_MS=$((LOSS * 100))
    echo "  推定ロス時間 : ${RECOVERY_MS}ms (${PING_INTERVAL}s間隔×${LOSS}パケット)"
elif [ "$LOSS" -eq 0 ]; then
    echo "  ロス率       : 0% ← フェイルオーバー成功"
fi

if [ -f /tmp/compare_t_down ] && [ -f /tmp/compare_t_up ]; then
    T_DOWN_V=$(cat /tmp/compare_t_down)
    T_UP_V=$(cat /tmp/compare_t_up)
    echo "  障害継続時間 : $((T_UP_V - T_DOWN_V)) ms"
fi

# ロス発生タイムウィンドウ抽出
echo ""
echo "--- ロス発生付近のping（前後10パケット）---"
if [ "$LOSS" -gt 0 ]; then
    grep -n "Request timeout\|Unreachable" "$PING_TS_LOG" | head -3 | while read -r hit; do
        LINENUM=$(echo "$hit" | cut -d: -f1)
        START=$((LINENUM - 5))
        [ "$START" -lt 1 ] && START=1
        sed -n "${START},$((LINENUM + 10))p" "$PING_TS_LOG" | sed 's/^/  /'
    done
else
    echo "  ロスなし (全パケット到達)"
    tail -5 "$PING_TS_LOG" | sed 's/^/  /'
fi

# ── 復旧後の状態 ─────────────────────────────────────────────────
sleep 3
echo ""
echo "--- 復旧後の経路 ---"
docker exec "$PING_SRC" traceroute -n -w 1 -q 1 "$PING_TARGET" 2>/dev/null | sed 's/^/  /' || true

docker exec frr-LER_Ingress vtysh -c "show ip ospf neighbor" 2>/dev/null | \
    grep -v "^$\|Neighbor" | sed 's/^  OSPF /  /' | sed 's/^/  /' || true

# ── CSV 出力 ─────────────────────────────────────────────────────
CSV="$RESULTS_DIR/summary.csv"
{
    echo "scenario,total,loss,loss_rate_pct,estimated_recovery_ms"
    LOSS_RATE_CSV=$(echo "scale=2; $LOSS * 100 / $TOTAL" | bc 2>/dev/null || echo "0")
    echo "${SCENARIO},${TOTAL},${LOSS},${LOSS_RATE_CSV},$((LOSS * 100))"
} > "$CSV"

echo ""
echo "$SEP"
echo "■ 計測完了: $RESULTS_DIR"
echo ""
echo "3シナリオ完了後に比較表を表示:"
echo "  sudo bash scripts/physical2_compare_report.sh"
