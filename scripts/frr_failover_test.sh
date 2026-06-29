#!/bin/bash
# フェイルオーバー自動テスト (SW1で実行)
# CR1障害シミュレーション → 経路変化の確認 → 自動復旧
# 使い方: sudo bash scripts/frr_failover_test.sh

SEP="─────────────────────────────────────────────────"

show_route() {
    echo "  LER_Ingress ルートテーブル (10.20.1.x):"
    docker exec LER_Ingress ip route show | grep 10.20.1 | sed 's/^/    /'
}

show_ospf_neighbor() {
    echo "  OSPF neighbors:"
    docker exec frr-LER_Ingress vtysh -c "show ip ospf neighbor" 2>/dev/null \
        | grep -E "Full|2-Way|Init|Down" | sed 's/^/    /' || true
}

show_bfd() {
    echo "  BFD peers:"
    docker exec frr-LER_Ingress vtysh -c "show bfd peers brief" 2>/dev/null \
        | grep -v "^$" | sed 's/^/    /' || true
}

show_trace() {
    echo "  Tx1 → Rx1 traceroute:"
    docker exec Tx1 traceroute -n -w 1 -q 1 10.20.1.2 2>/dev/null | sed 's/^/    /'
}

restore_routes() {
    # interfaceがupした後に静的ルートを再追加（Linuxカーネルは自動復元しないため）
    docker exec LER_Ingress ip route replace 10.20.1.0/24 via 10.0.1.2 dev leri-cr1 metric 1 2>/dev/null || true
    docker exec LER_Ingress ip route replace 10.20.2.0/24 via 10.0.1.2 dev leri-cr1 metric 3 2>/dev/null || true
    docker exec LER_Ingress ip route replace 10.20.3.0/24 via 10.0.1.2 dev leri-cr1 metric 3 2>/dev/null || true
}

echo "$SEP"
echo "■ フェイルオーバー自動テスト開始"
echo "$SEP"

echo ""
echo "【1】正常時の状態"
show_route
echo ""
show_ospf_neighbor
echo ""
show_bfd
echo ""
show_trace

echo ""
echo "$SEP"
echo "【2】CR1リンクをダウン (leri-cr1 down)"
T_DOWN=$(date +%T.%3N)
docker exec LER_Ingress ip link set leri-cr1 down
echo "  ${T_DOWN}  leri-cr1 DOWN"

# BFDが障害を検出するまで少し待つ（300ms×3=900ms）
sleep 1.5

echo ""
echo "  ダウン後のルートテーブル (leri-cr1経由が消えてleri-cr2が優先に):"
show_route

echo ""
echo "  Tx1 → Rx1 ping 5回 (0%ロスなら自動切替成功):"
docker exec Tx1 ping -c 5 -W 1 10.20.1.2 | tail -3 | sed 's/^/    /'

echo ""
echo "  ダウン後のOSPF状態:"
show_ospf_neighbor

echo ""
echo "  ダウン後のtraceroute (CR経路の変化を確認):"
show_trace

echo ""
echo "$SEP"
echo "【3】CR1リンクを復旧 (leri-cr1 up)"
docker exec LER_Ingress ip link set leri-cr1 up
echo "  $(date +%T.%3N)  leri-cr1 UP"
sleep 2

restore_routes
echo "  (静的ルート再追加済み)"

echo ""
echo "  復旧後のルートテーブル (metric 1のルートが戻ったか):"
show_route

echo ""
echo "  復旧後traceroute:"
show_trace

echo ""
echo "$SEP"
echo "■ テスト完了"
echo ""
echo "見方:"
echo "  ・ダウン前: '10.20.1.0/24 via leri-cr1 metric 1' が最優先"
echo "  ・ダウン後: leri-cr1ルートが消え 'via leri-cr2 metric 2' が有効化"
echo "  ・復旧後:   'via leri-cr1 metric 1' が戻り元の経路に"
echo "  ・pingが0%ロスなら高速フェイルオーバー成功"
