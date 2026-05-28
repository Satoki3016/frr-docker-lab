#!/bin/bash
# MPLS静的LSP設定（virttrx版）
#
# Tunnel 1: AF41 → Rx1(10.20.1.1): LER_Ingress_ns → CoreRouter1_ns → LER_Egress_ns
# Tunnel 2: AF42 → Rx2(10.20.2.1): LER_Ingress_ns → CoreRouter2_ns → LER_Egress_ns
# Tunnel 3: AF43 → Rx3(10.20.3.1): LER_Ingress_ns → CoreRouter3_ns → LER_Egress_ns
#
set -e

echo "=== MPLSモジュール確認 ==="
modprobe mpls_router 2>/dev/null || echo "  [WARN] mpls_router not available"
modprobe mpls_iptunnel 2>/dev/null || echo "  [WARN] mpls_iptunnel not available"
echo "  完了"

echo ""
echo "=== MPLS sysctl 有効化 ==="
for ns in LER_Ingress_ns CoreRouter1_ns CoreRouter2_ns CoreRouter3_ns LER_Egress_ns; do
    ip netns exec "$ns" sysctl -qw net.mpls.platform_labels=65536
done

# コアリンクのMPLS入力有効化
for dev in leri-cr1 leri-cr2 leri-cr3; do
    ip netns exec LER_Ingress_ns sysctl -qw net.mpls.conf.${dev}.input=1
    echo "  LER_Ingress_ns:$dev input=1"
done
for dev in cr1-leri cr1-lere; do
    ip netns exec CoreRouter1_ns sysctl -qw net.mpls.conf.${dev}.input=1
done
for dev in cr2-leri cr2-lere; do
    ip netns exec CoreRouter2_ns sysctl -qw net.mpls.conf.${dev}.input=1
done
for dev in cr3-leri cr3-lere; do
    ip netns exec CoreRouter3_ns sysctl -qw net.mpls.conf.${dev}.input=1
done
for dev in lere-cr1 lere-cr2 lere-cr3; do
    ip netns exec LER_Egress_ns sysctl -qw net.mpls.conf.${dev}.input=1
    echo "  LER_Egress_ns:$dev input=1"
done

echo ""
echo "=== Ingress LSP (LER_Ingress_ns) ==="
ip netns exec LER_Ingress_ns \
    ip route replace 10.20.1.1/32 encap mpls 100 via 10.0.1.2 dev leri-cr1
echo "  Tunnel1: 10.20.1.1/32 encap mpls 100 → 10.0.1.2 (CR1)"

ip netns exec LER_Ingress_ns \
    ip route replace 10.20.2.1/32 encap mpls 200 via 10.0.3.2 dev leri-cr2
echo "  Tunnel2: 10.20.2.1/32 encap mpls 200 → 10.0.3.2 (CR2)"

ip netns exec LER_Ingress_ns \
    ip route replace 10.20.3.1/32 encap mpls 300 via 10.0.5.2 dev leri-cr3
echo "  Tunnel3: 10.20.3.1/32 encap mpls 300 → 10.0.5.2 (CR3)"

echo ""
echo "=== Transit LSP ==="
ip netns exec CoreRouter1_ns ip -f mpls route replace 100 as 101 via inet 10.0.2.2 dev cr1-lere
echo "  CR1: swap 100 → 101"
ip netns exec CoreRouter2_ns ip -f mpls route replace 200 as 201 via inet 10.0.4.2 dev cr2-lere
echo "  CR2: swap 200 → 201"
ip netns exec CoreRouter3_ns ip -f mpls route replace 300 as 301 via inet 10.0.6.2 dev cr3-lere
echo "  CR3: swap 300 → 301"

echo ""
echo "=== Egress LSP (LER_Egress_ns) ==="
ip netns exec LER_Egress_ns ip -f mpls route replace 101 via inet 10.20.1.1 dev lere-rx1
echo "  pop 101 → 10.20.1.1 (Rx1, veth)"

# Rx2/Rx3: veth経由
ip netns exec LER_Egress_ns ip -f mpls route replace 201 via inet 10.20.2.1 dev lere-rx2
echo "  pop 201 → 10.20.2.1 (Rx2, veth)"
ip netns exec LER_Egress_ns ip -f mpls route replace 301 via inet 10.20.3.1 dev lere-rx3
echo "  pop 301 → 10.20.3.1 (Rx3, veth)"

echo ""
echo "=== MPLS設定確認 ==="
echo "--- LER_Ingress_ns ---"
ip netns exec LER_Ingress_ns ip route show | grep "encap mpls"
echo "--- CoreRouter1_ns ---"
ip netns exec CoreRouter1_ns ip -f mpls route show
echo "--- LER_Egress_ns ---"
ip netns exec LER_Egress_ns ip -f mpls route show

echo ""
echo "MPLS設定完了"
echo "疎通確認: ip netns exec Tx1_ns ping -c3 10.20.1.1"
