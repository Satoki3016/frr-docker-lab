#!/bin/bash
<<<<<<< HEAD
# MPLS静的LSP設定
#
# Tunnel 1: AF41 → Rx1(10.20.1.2): LER_Ingress → CoreRouter1 → LER_Egress
# Tunnel 2: AF42 → Rx2(10.20.2.2): LER_Ingress → CoreRouter2 → LER_Egress
# Tunnel 3: AF43 → Rx3(10.20.3.2): LER_Ingress → CoreRouter3 → LER_Egress
=======
# MPLS静的LSP設定 - OMNeT++ LER_Ingress_traffic.xml / LER_Ingress_fec.xml に対応
#
# Tunnel 1: AF41 → Rx1(10.2.1.2): LER_Ingress → CoreRouter1 → LER_Egress
#   push=100 (LER_Ingress), swap=100→101 (CR1), pop=101 (LER_Egress)
# Tunnel 2: AF42 → Rx2(10.2.2.2): LER_Ingress → CoreRouter2 → LER_Egress
#   push=200 (LER_Ingress), swap=200→201 (CR2), pop=201 (LER_Egress)
# Tunnel 3: AF43 → Rx3(10.2.3.2): LER_Ingress → CoreRouter2 → LER_Egress
#   push=300 (LER_Ingress), swap=300→301 (CR2), pop=301 (LER_Egress)
>>>>>>> a871d29236fc25033b139708afa500660335c698
#
set -e
source "$(dirname "$0")/00_env.sh"

<<<<<<< HEAD
echo "=== MPLSモジュール確認 ==="
if ! /sbin/modprobe mpls_router 2>/dev/null; then
    echo "  [WARN] mpls_router モジュールが利用不可"
fi
/sbin/modprobe mpls_iptunnel 2>/dev/null || true
echo "  完了"

echo ""
echo "=== MPLS sysctl 有効化 ==="
for ns in LER_Ingress CoreRouter1 CoreRouter2 CoreRouter3 LER_Egress; do
    ip netns exec "$ns" sysctl -qw net.mpls.platform_labels=65536
done

for dev in leri-cr1 leri-cr2 leri-cr3; do
    ip netns exec LER_Ingress sysctl -qw net.mpls.conf.${dev}.input=1
    echo "  LER_Ingress:$dev input=1"
done
for dev in cr1-leri cr1-lere; do
    ip netns exec CoreRouter1 sysctl -qw net.mpls.conf.${dev}.input=1
    echo "  CoreRouter1:$dev input=1"
done
for dev in cr2-leri cr2-lere; do
    ip netns exec CoreRouter2 sysctl -qw net.mpls.conf.${dev}.input=1
    echo "  CoreRouter2:$dev input=1"
done
for dev in cr3-leri cr3-lere; do
    ip netns exec CoreRouter3 sysctl -qw net.mpls.conf.${dev}.input=1
    echo "  CoreRouter3:$dev input=1"
done
for dev in lere-cr1 lere-cr2 lere-cr3; do
    ip netns exec LER_Egress sysctl -qw net.mpls.conf.${dev}.input=1
    echo "  LER_Egress:$dev input=1"
done

echo ""
echo "=== Ingress LSP (LER_Ingress) ==="
ip netns exec LER_Ingress \
    ip route replace 10.20.1.2/32 encap mpls 100 via 10.0.1.2 dev leri-cr1
echo "  Tunnel1: 10.20.1.2/32 encap mpls 100 → 10.0.1.2 (CR1)"

ip netns exec LER_Ingress \
    ip route replace 10.20.2.2/32 encap mpls 200 via 10.0.3.2 dev leri-cr2
echo "  Tunnel2: 10.20.2.2/32 encap mpls 200 → 10.0.3.2 (CR2)"

ip netns exec LER_Ingress \
    ip route replace 10.20.3.2/32 encap mpls 300 via 10.0.5.2 dev leri-cr3
echo "  Tunnel3: 10.20.3.2/32 encap mpls 300 → 10.0.5.2 (CR3)"

echo ""
echo "=== Transit LSP ==="
ip netns exec CoreRouter1 ip -f mpls route replace 100 as 101 via inet 10.0.2.2 dev cr1-lere
echo "  CR1: swap 100 → 101"
ip netns exec CoreRouter2 ip -f mpls route replace 200 as 201 via inet 10.0.4.2 dev cr2-lere
echo "  CR2: swap 200 → 201"
ip netns exec CoreRouter3 ip -f mpls route replace 300 as 301 via inet 10.0.6.2 dev cr3-lere
echo "  CR3: swap 300 → 301"

echo ""
echo "=== Egress LSP (LER_Egress) ==="
ip netns exec LER_Egress ip -f mpls route replace 101 via inet 10.20.1.2 dev rx1-out
echo "  pop 101 → 10.20.1.2 (Rx1)"
ip netns exec LER_Egress ip -f mpls route replace 201 via inet 10.20.2.2 dev rx2-out
echo "  pop 201 → 10.20.2.2 (Rx2)"
ip netns exec LER_Egress ip -f mpls route replace 301 via inet 10.20.3.2 dev rx3-out
echo "  pop 301 → 10.20.3.2 (Rx3)"

echo ""
echo "=== MPLS設定確認 ==="
echo "--- LER_Ingress ---"
ip netns exec LER_Ingress ip route show | grep "encap mpls"
echo "--- CoreRouter1 ---"
ip netns exec CoreRouter1 ip -f mpls route show
echo "--- LER_Egress ---"
ip netns exec LER_Egress ip -f mpls route show

echo ""
echo "MPLS LSP設定完了"
=======
# ----------------------------------------------------------------
# 1. MPLSカーネルモジュール確認 (ホスト側で実行)
# ----------------------------------------------------------------
echo "=== MPLSモジュール確認 ==="
modprobe mpls_router
modprobe mpls_iptunnel
echo "  mpls_router, mpls_iptunnel loaded"

# ----------------------------------------------------------------
# 2. 各コンテナでMPLS有効化
# ----------------------------------------------------------------
echo ""
echo "=== MPLS sysctl 有効化 ==="

for ns in LER_Ingress CoreRouter1 CoreRouter2 CoreRouter3 LER_Egress; do
    docker exec "$ns" sysctl -qw net.mpls.platform_labels=65536
done

for dev in leri-cr1 leri-cr2 leri-cr3; do
    docker exec LER_Ingress sysctl -qw net.mpls.conf.${dev}.input=1
    echo "  LER_Ingress:$dev input=1"
done

for dev in cr1-leri cr1-lere; do
    docker exec CoreRouter1 sysctl -qw net.mpls.conf.${dev}.input=1
    echo "  CoreRouter1:$dev input=1"
done

for dev in cr2-leri cr2-lere; do
    docker exec CoreRouter2 sysctl -qw net.mpls.conf.${dev}.input=1
    echo "  CoreRouter2:$dev input=1"
done

for dev in cr3-leri cr3-lere; do
    docker exec CoreRouter3 sysctl -qw net.mpls.conf.${dev}.input=1
    echo "  CoreRouter3:$dev input=1"
done

for dev in lere-cr1 lere-cr2 lere-cr3; do
    docker exec LER_Egress sysctl -qw net.mpls.conf.${dev}.input=1
    echo "  LER_Egress:$dev input=1"
done

# ----------------------------------------------------------------
# 3. Ingress: LER_Ingress - FEC → ラベル付与 (push)
# ----------------------------------------------------------------
echo ""
echo "=== Ingress LSP (LER_Ingress) ==="

docker exec LER_Ingress \
    ip route replace 10.2.1.2/32 encap mpls 100 via 10.1.3.2 dev leri-cr1
echo "  Tunnel1: 10.2.1.2/32 encap mpls 100 → 10.1.3.2 (CR1)"

docker exec LER_Ingress \
    ip route replace 10.2.2.2/32 encap mpls 200 via 10.1.4.2 dev leri-cr2
echo "  Tunnel2: 10.2.2.2/32 encap mpls 200 → 10.1.4.2 (CR2) MediumSpeedLink"

docker exec LER_Ingress \
    ip route replace 10.2.3.2/32 encap mpls 300 via 10.1.5.2 dev leri-cr3
echo "  Tunnel3: 10.2.3.2/32 encap mpls 300 → 10.1.5.2 (CR3) LowSpeedLink"

# ----------------------------------------------------------------
# 4. Transit: CoreRouter1 - label swap (100 → 101)
# ----------------------------------------------------------------
echo ""
echo "=== Transit LSP (CoreRouter1) ==="

docker exec CoreRouter1 \
    ip -f mpls route replace 100 as 101 via inet 10.2.10.1 dev cr1-lere
echo "  swap 100 → 101 via 10.2.10.1 (LER_Egress)"

# ----------------------------------------------------------------
# 5. Transit: CoreRouter2 - label swap (200→201, 300→301)
# ----------------------------------------------------------------
echo ""
echo "=== Transit LSP (CoreRouter2) ==="

docker exec CoreRouter2 \
    ip -f mpls route replace 200 as 201 via inet 10.2.11.1 dev cr2-lere
echo "  swap 200 → 201 via 10.2.11.1 (LER_Egress)"

echo ""
echo "=== Transit LSP (CoreRouter3) ==="

docker exec CoreRouter3 \
    ip -f mpls route replace 300 as 301 via inet 10.2.12.1 dev cr3-lere
echo "  swap 300 → 301 via 10.2.12.1 (LER_Egress)"

# ----------------------------------------------------------------
# 6. Egress: LER_Egress - label pop → IP転送
# ----------------------------------------------------------------
echo ""
echo "=== Egress LSP (LER_Egress) ==="

docker exec LER_Egress \
    ip -f mpls route replace 101 via inet 10.2.1.2 dev lere-rx1
echo "  pop 101 → 10.2.1.2 (Rx1)"

docker exec LER_Egress \
    ip -f mpls route replace 201 via inet 10.2.2.2 dev lere-rx2
echo "  pop 201 → 10.2.2.2 (Rx2)"

docker exec LER_Egress \
    ip -f mpls route replace 301 via inet 10.2.3.2 dev lere-rx3
echo "  pop 301 → 10.2.3.2 (Rx3)"

# ----------------------------------------------------------------
# 7. 確認
# ----------------------------------------------------------------
echo ""
echo "=== MPLS設定確認 ==="
echo "--- LER_Ingress ---"
docker exec LER_Ingress ip route show | grep "encap mpls"

echo "--- CoreRouter1 ---"
docker exec CoreRouter1 ip -f mpls route show

echo "--- CoreRouter2 ---"
docker exec CoreRouter2 ip -f mpls route show

echo "--- LER_Egress ---"
docker exec LER_Egress ip -f mpls route show

echo ""
echo "MPLS LSP設定完了"
echo "疎通確認: docker exec Tx1 ping -c3 10.2.1.2"
>>>>>>> a871d29236fc25033b139708afa500660335c698
