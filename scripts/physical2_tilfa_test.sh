#!/bin/bash
# TI-LFA フェイルオーバーテスト (SW1で実行)
# CR1リンクをダウンさせてフェイルオーバー時間を計測
# 使い方: sudo bash scripts/physical2_tilfa_test.sh
set -e

SEP="═══════════════════════════════════════════════════"
PING_TARGET="10.20.1.2"   # Rx1
PING_SRC_CTR="Tx1"

# ── ユーティリティ ────────────────────────────────────────────
show_route() {
    echo "  LER_Ingress IPルート (10.20.1.x):"
    docker exec LER_Ingress ip route show | grep "10.20.1" | sed 's/^/    /' || true
}

show_mpls() {
    echo "  LER_Ingress MPLSテーブル (SR/LDPエントリのみ):"
    docker exec frr-LER_Ingress vtysh -c "show mpls table" 2>/dev/null | grep -E "SR|LDP" | head -10 | sed 's/^/    /' || true
}

show_ospf_neighbor() {
    echo "  OSPF neighbors (LER_Ingress):"
    docker exec frr-LER_Ingress vtysh -c "show ip ospf neighbor" 2>/dev/null | \
        grep -v "^$\|Neighbor" | sed 's/^/    /' || true
}

show_bfd() {
    echo "  BFD peers (frr-LER_Ingress):"
    docker exec frr-LER_Ingress vtysh -c "show bfd peers brief" 2>/dev/null | \
        grep -v "^$" | sed 's/^/    /' || true
}

# ── テスト開始 ────────────────────────────────────────────────
echo "$SEP"
echo "■ TI-LFA フェイルオーバーテスト開始"
echo "  対象: CR1 (leri-cr1) ダウン → CR2/CR3 で継続"
echo "$SEP"

echo ""
echo "【1】正常時の状態"
show_route
echo ""
show_ospf_neighbor
echo ""
show_bfd

echo ""
echo "  Tx1 → Rx1 traceroute (正常経路):"
docker exec "$PING_SRC_CTR" traceroute -n -w 1 -q 1 "$PING_TARGET" 2>/dev/null | sed 's/^/    /' || true

echo ""
echo "$SEP"
echo "【2】連続ping開始 → leri-cr1 ダウン"
echo "  BFD検出時間: 50ms × 3 = 150ms (フェイルオーバー最低要件)"
echo ""

# バックグラウンドでping実行（タイムスタンプ付き）
PING_LOG="/tmp/tilfa_ping_$$.log"
docker exec "$PING_SRC_CTR" ping -i 0.1 -W 1 "$PING_TARGET" 2>/dev/null | \
    while IFS= read -r line; do printf "%s %s\n" "$(date +%T.%3N)" "$line"; done \
    > "$PING_LOG" &
PING_PID=$!
echo "  pingプロセス: PID=$PING_PID  ログ: $PING_LOG"

sleep 1  # pingが安定するまで待機

echo ""
echo "  [$(date +%T.%3N)] leri-cr1 DOWN ↓"
T_DOWN=$(date +%s%3N)
docker exec LER_Ingress ip link set leri-cr1 down

sleep 3  # フェイルオーバー完了を待つ

echo "  [$(date +%T.%3N)] leri-cr1 UP ↑"
T_UP=$(date +%s%3N)
docker exec LER_Ingress ip link set leri-cr1 up

sleep 3  # 復旧完了を待つ

# ping停止
kill "$PING_PID" 2>/dev/null || true
sleep 0.5

echo ""
echo "=== ping結果 ==="
echo "  ダウン時間: $((T_UP - T_DOWN)) ms"
echo ""

# ロスしたパケットを抽出
LOSS_COUNT=$(grep -c "Request timeout\|No answer\|100% packet loss" "$PING_LOG" 2>/dev/null || echo 0)
TOTAL_COUNT=$(grep -c "bytes from\|Request timeout" "$PING_LOG" 2>/dev/null || echo 0)

echo "  総ping数: $TOTAL_COUNT"
echo "  ロスト数: $LOSS_COUNT"

if [ "$TOTAL_COUNT" -gt 0 ]; then
    LOSS_RATE=$(echo "scale=1; $LOSS_COUNT * 100 / $TOTAL_COUNT" | bc 2>/dev/null || echo "?")
    echo "  ロス率: ${LOSS_RATE}%"
fi

echo ""
echo "  タイムスタンプ付きpingログ (ダウン前後):"
grep -E "$(date +%H:%M)" "$PING_LOG" | tail -20 | sed 's/^/    /' || \
    cat "$PING_LOG" | tail -20 | sed 's/^/    /'

echo ""
echo "$SEP"
echo "【3】復旧後の状態確認"
echo ""
show_route
echo ""
show_ospf_neighbor
echo ""

echo "  Tx1 → Rx1 traceroute (復旧後経路):"
docker exec "$PING_SRC_CTR" traceroute -n -w 1 -q 1 "$PING_TARGET" 2>/dev/null | sed 's/^/    /' || true

echo ""
echo "$SEP"
echo "■ テスト完了"
echo ""
echo "判定基準:"
echo "  ロス率 0%           → フェイルオーバー成功 (ping間隔 100ms以内)"
echo "  ロス数 ≤ 2パケット  → 150ms 以内の切替を示す (100ms間隔×2=200ms)"
echo "  ロス数 ≤ 1パケット  → 100ms 以内の切替"
echo ""
echo "  ロス率 > 0% の場合は 'show mpls table' でSRバックアップ経路を確認:"
echo "  docker exec frr-LER_Ingress vtysh -c 'show mpls table'"

# クリーンアップ
rm -f "$PING_LOG"
