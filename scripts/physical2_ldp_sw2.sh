#!/bin/bash
# Phase 1: LDP（動的ラベル配布）セットアップ (SW2)
# 実行: SW2上で  sudo bash scripts/physical2_ldp_sw2.sh
set -e

FRR_IMAGE="${FRR_IMAGE:-frrouting/frr}"
LO_LER_EGRESS="10.255.1.5"

# ── 1. Loopback IP + MPLSカーネル設定 ────────────────────────────
echo "=== [SW2] Loopback IP / MPLS設定 ==="
docker exec LER_Egress ip addr add "${LO_LER_EGRESS}/32" dev lo 2>/dev/null || true
docker exec LER_Egress sysctl -qw net.mpls.conf.lo.input=1
for iface in lere-cr1 lere-cr2 lere-cr3 lere-rx1 lere-rx2 lere-rx3; do
    docker exec LER_Egress sysctl -qw "net.mpls.conf.${iface}.input=1" 2>/dev/null || true
done
echo "  LER_Egress: lo=${LO_LER_EGRESS}/32  mpls_input=1"

# ── 2. 静的MPLSラベルを削除 ────────────────────────────────────
echo ""
echo "=== [SW2] 静的MPLSラベル削除 ==="
docker exec LER_Egress ip -f mpls route del 101 2>/dev/null || true
docker exec LER_Egress ip -f mpls route del 201 2>/dev/null || true
docker exec LER_Egress ip -f mpls route del 301 2>/dev/null || true
echo "  [ok] 静的pop-label (101/201/301) 削除"

# ── 3. FRRコンテナ更新（OSPF設定のみ、LDPはvtyshで後設定） ──────────────────────────────
# 注: interface loとnetwork文の混在はFRRが拒否するため interface lo ブロックは書かない
echo ""
echo "=== [SW2] FRRコンテナ更新 ==="

dir="/tmp/frr-LER_Egress"
mkdir -p "$dir"

cat > "${dir}/daemons" << 'DAEMONS'
zebra=yes
ospfd=yes
bfdd=yes
ldpd=yes
staticd=yes
vtysh_enable=yes
DAEMONS

echo "service integrated-vtysh-config" > "${dir}/vtysh.conf"

cat > "${dir}/frr.conf" << FRRCONF
frr version 8.4
frr defaults traditional
hostname LER_Egress
log syslog informational
!
interface lere-cr1
 ip ospf bfd
 ip ospf bfd profile fast
 ip ospf hello-interval 1
 ip ospf dead-interval 3
 ip ospf network point-to-point
!
interface lere-cr2
 ip ospf bfd
 ip ospf bfd profile fast
 ip ospf hello-interval 1
 ip ospf dead-interval 3
 ip ospf network point-to-point
!
interface lere-cr3
 ip ospf bfd
 ip ospf bfd profile fast
 ip ospf hello-interval 1
 ip ospf dead-interval 3
 ip ospf network point-to-point
!
bfd
 profile fast
  receive-interval 50
  transmit-interval 50
  detect-multiplier 3
 !
!
router ospf
 ospf router-id ${LO_LER_EGRESS}
 network 10.0.2.0/30 area 0
 network 10.0.4.0/30 area 0
 network 10.0.6.0/30 area 0
 network 10.20.1.0/30 area 0
 network 10.20.2.0/30 area 0
 network 10.20.3.0/30 area 0
 network ${LO_LER_EGRESS}/32 area 0
!
FRRCONF

chmod 777 "$dir"
chmod 644 "${dir}"/*

docker rm -f "frr-LER_Egress" 2>/dev/null || true
docker run -d --name "frr-LER_Egress" \
    --network "container:LER_Egress" \
    --privileged \
    -v "${dir}:/etc/frr" \
    "$FRR_IMAGE"
echo "  [ok] frr-LER_Egress (ldpd有効)"

# ── 4. OSPF収束待ち ─────────────────────────────────────────────
echo ""
echo "=== [SW2] OSPF収束待ち (20秒) ==="
sleep 20

echo ""
echo "=== [SW2] OSPF状態確認 ==="
docker exec frr-LER_Egress vtysh -c "show ip ospf neighbor" 2>/dev/null || echo "  (まだ収束中)"

# ── 5. LDP設定（vtysh経由） ─────────────────────────────────────
echo ""
echo "=== [SW2] LDP設定 (vtysh) ==="
{
    echo "configure terminal"
    echo "mpls ldp"
    echo " router-id ${LO_LER_EGRESS}"
    echo " address-family ipv4"
    echo "  discovery transport-address ${LO_LER_EGRESS}"
    echo "  interface lere-cr1"
    echo "  interface lere-cr2"
    echo "  interface lere-cr3"
    echo " exit-address-family"
    echo "end"
    echo "write memory"
} | docker exec -i frr-LER_Egress vtysh
echo "  [ok] frr-LER_Egress LDP設定完了"

# ── 6. LDP収束待ち・確認 ────────────────────────────────────────
echo ""
echo "=== [SW2] LDP収束待ち (15秒) ==="
sleep 15

echo ""
echo "=== [SW2] LDP状態確認 ==="
echo "--- LDP neighbors (LER_Egress) ---"
docker exec frr-LER_Egress vtysh -c "show mpls ldp neighbor" 2>/dev/null || \
    echo "  (まだ収束中)"
echo ""
echo "--- LDP bindings ---"
docker exec frr-LER_Egress vtysh -c "show mpls ldp binding" 2>/dev/null | head -20 || true

echo ""
echo "=== [SW2] 完了 ==="
echo "SW1での確認: docker exec frr-LER_Ingress vtysh -c 'show mpls ldp neighbor'"
echo "疎通確認: docker exec Tx1 ping -c3 10.20.1.2 (SW1で実行)"
