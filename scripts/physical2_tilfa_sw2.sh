#!/bin/bash
# Phase 3: TI-LFA セットアップ (SW2)
# 実行: SW2上で  sudo bash scripts/physical2_tilfa_sw2.sh
set -e

LO_LER_EGRESS="10.255.1.5"

echo "=== [SW2] TI-LFA 有効化 ==="
{
    echo "configure terminal"
    echo "router ospf"
    echo " fast-reroute enable lfib-cspf"
    echo "exit"
    echo "end"
    echo "write memory"
} | docker exec -i frr-LER_Egress vtysh
echo "  [ok] frr-LER_Egress"

echo ""
echo "=== [SW2] TI-LFA SPF収束待ち (10秒) ==="
sleep 10

echo ""
echo "=== [SW2] 状態確認 ==="
echo "--- OSPF route (LER_Egress) ---"
docker exec frr-LER_Egress vtysh -c "show ip ospf route" 2>/dev/null | \
    grep -E "10\.255\.|10\.10\.|backup" | head -20 || true

echo ""
echo "--- MPLSテーブル (LER_Egress) ---"
docker exec frr-LER_Egress vtysh -c "show mpls table" 2>/dev/null | head -20

echo ""
echo "=== [SW2] 完了 ==="
echo "フェイルオーバーテスト: sudo bash ~/scripts/physical2_tilfa_test.sh  (SW1で実行)"
