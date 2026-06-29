#!/bin/bash
# Phase 2: SR-MPLS（Segment Routing）セットアップ (SW2)
# 前提: physical2_ldp_sw2.sh が実行済みであること
# 実行: SW2上で  sudo bash scripts/physical2_sr_sw2.sh
set -e

LO_LER_EGRESS="10.255.1.5"
SRGB_LOW=16000
SRGB_HIGH=23999
NODE_MSD=8
SR_INDEX=5   # SID 16005

SID=$((SRGB_LOW + SR_INDEX))

echo "=== [SW2] SR-MPLS Node SID設定 ==="
echo "  SR設定: frr-LER_Egress  loopback=${LO_LER_EGRESS}/32  Node-SID=${SID} (index=${SR_INDEX})"
{
    echo "configure terminal"
    echo "router ospf"
    echo " capability opaque"
    echo " mpls-te on"
    echo " mpls-te router-address ${LO_LER_EGRESS}"
    echo " segment-routing on"
    echo " segment-routing global-block ${SRGB_LOW} ${SRGB_HIGH}"
    echo " segment-routing node-msd ${NODE_MSD}"
    echo " segment-routing prefix ${LO_LER_EGRESS}/32 index ${SR_INDEX}"
    echo "exit"
    echo "end"
    echo "write memory"
} | docker exec -i frr-LER_Egress vtysh
echo "  [ok] frr-LER_Egress"

# ── SR収束待ち ────────────────────────────────────────────────────
echo ""
echo "=== [SW2] SR収束待ち (15秒) ==="
sleep 15

# ── 状態確認 ─────────────────────────────────────────────────────
echo ""
echo "=== [SW2] SR状態確認 ==="

echo "--- OSPF Opaque-Area LSA (SR Prefix SID確認) ---"
docker exec frr-LER_Egress vtysh -c "show ip ospf database opaque-area self-originate" 2>/dev/null | \
    grep -E "LS Type|Link State|Prefix|SID|Index|Algo" | head -20 || true

echo ""
echo "--- MPLS転送テーブル (LER_Egress) ---"
docker exec frr-LER_Egress vtysh -c "show mpls table" 2>/dev/null | head -20

echo ""
echo "=== [SW2] 完了 ==="
echo "疎通確認: docker exec Tx1 ping -c3 10.20.1.2  (SW1で実行)"
echo "SW1での確認:"
echo "  docker exec frr-LER_Ingress vtysh -c 'show mpls table'"
echo "  → SID 16005 (LER_Egress) へのエントリが増えているはず"
