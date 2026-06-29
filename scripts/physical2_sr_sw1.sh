#!/bin/bash
# Phase 2: SR-MPLS（Segment Routing）セットアップ (SW1)
# 前提: physical2_ldp_sw1.sh が実行済みであること
# 実行: SW1上で  sudo bash scripts/physical2_sr_sw1.sh
set -e

declare -A LO_IP=(
    [LER_Ingress]="10.255.1.1"
    [CR1]="10.255.1.2"
    [CR2]="10.255.1.3"
    [CR3]="10.255.1.4"
)

# SRGB (Segment Routing Global Block): 16000-23999
# Node SID = SRGB_LOW + index
SRGB_LOW=16000
SRGB_HIGH=23999
NODE_MSD=8  # Maximum SID Depth (MPLSスタック最大深さ)

declare -A SR_INDEX=(
    [LER_Ingress]=1   # SID 16001
    [CR1]=2           # SID 16002
    [CR2]=3           # SID 16003
    [CR3]=4           # SID 16004
    # LER_Egress=5    # SID 16005 (SW2で設定)
)

configure_sr() {
    local name=$1
    local lo="${LO_IP[$name]}"
    local idx="${SR_INDEX[$name]}"
    local sid=$((SRGB_LOW + idx))
    echo "  SR設定: frr-${name}  loopback=${lo}/32  Node-SID=${sid} (index=${idx})"
    {
        echo "configure terminal"
        echo "router ospf"
        echo " capability opaque"
        echo " mpls-te on"
        echo " mpls-te router-address ${lo}"
        echo " segment-routing on"
        echo " segment-routing global-block ${SRGB_LOW} ${SRGB_HIGH}"
        echo " segment-routing node-msd ${NODE_MSD}"
        echo " segment-routing prefix ${lo}/32 index ${idx}"
        echo "exit"
        echo "end"
        echo "write memory"
    } | docker exec -i "frr-${name}" vtysh
    echo "  [ok] frr-${name}"
}

echo "=== [SW1] SR-MPLS Node SID設定 ==="
for name in LER_Ingress CR1 CR2 CR3; do
    configure_sr "$name"
done

# ── SR収束待ち ────────────────────────────────────────────────────
echo ""
echo "=== [SW1] SR収束待ち (15秒) ==="
sleep 15

# ── 状態確認 ─────────────────────────────────────────────────────
echo ""
echo "=== [SW1] SR状態確認 ==="

echo "--- OSPF Opaque-Area LSA (SR Prefix SID確認) ---"
docker exec frr-LER_Ingress vtysh -c "show ip ospf database opaque-area self-originate" 2>/dev/null | \
    grep -E "LS Type|Link State|Prefix|SID|Index|Algo" | head -20 || true

echo ""
echo "--- MPLS転送テーブル (LER_Ingress) ---"
docker exec frr-LER_Ingress vtysh -c "show mpls table" 2>/dev/null | head -30

echo ""
echo "--- LDP + SR 混在状態のラベル確認 ---"
docker exec frr-LER_Ingress vtysh -c "show mpls ldp binding" 2>/dev/null | \
    grep -E "10\.255\." | head -20 || true

echo ""
echo "=== [SW1] 完了 ==="
cat << 'USAGE'

■ SW2でも実行: sudo bash ~/scripts/physical2_sr_sw2.sh

■ Node SID一覧 (SRGB: 16000-23999):
  LER_Ingress : 10.255.1.1/32 → index 1 → SID 16001
  CR1         : 10.255.1.2/32 → index 2 → SID 16002
  CR2         : 10.255.1.3/32 → index 3 → SID 16003
  CR3         : 10.255.1.4/32 → index 4 → SID 16004
  LER_Egress  : 10.255.1.5/32 → index 5 → SID 16005

■ SR確認コマンド:
  docker exec frr-LER_Ingress vtysh -c "show ip ospf segment-routing"
  docker exec frr-LER_Ingress vtysh -c "show mpls table"
  docker exec frr-CR1 vtysh -c "show ip ospf segment-routing"

■ SRによるパス指定例 (SW1→Rx1をCR1経由で明示):
  SIDスタック: [16002 (CR1), 16005 (LER_Egress)]
  → LER_IngressでMPLSパケットに2段スタックをpush
USAGE
