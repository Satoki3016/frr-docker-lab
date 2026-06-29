#!/bin/bash
# MPLS静的LSP設定（SONiC用 - root namespace版）
# LER_Ingress/Egress は root namespace で動作
set -e

echo "=== MPLSモジュール確認 ==="
/sbin/modprobe mpls_router    2>/dev/null || true
/sbin/modprobe mpls_iptunnel  2>/dev/null || true
echo "  完了"

echo ""
echo "=== MPLS sysctl 有効化 ==="
sysctl -qw net.mpls.platform_labels=65536
# root ns: lere-cr1/2/3 は MPLS ラベル付きパケットを受信する（LER_Egress）
for dev in lere-cr1 lere-cr2 lere-cr3; do
    sysctl -qw net.mpls.conf.${dev}.input=1
    echo "  root:$dev input=1"
done

for ns in CoreRouter1 CoreRouter2 CoreRouter3; do
    ip netns exec "$ns" sysctl -qw net.mpls.platform_labels=65536
done
for dev in cr1-leri cr1-lere; do ip netns exec CoreRouter1 sysctl -qw net.mpls.conf.${dev}.input=1; done
for dev in cr2-leri cr2-lere; do ip netns exec CoreRouter2 sysctl -qw net.mpls.conf.${dev}.input=1; done
for dev in cr3-leri cr3-lere; do ip netns exec CoreRouter3 sysctl -qw net.mpls.conf.${dev}.input=1; done
echo "  CoreRouter1/2/3 input=1"

echo ""
echo "=== Ingress LSP (root ns = LER_Ingress) ==="
ip route replace 10.20.1.2/32 encap mpls 100 via 10.0.1.2 dev leri-cr1
echo "  Tunnel1: 10.20.1.2/32 encap mpls 100 → leri-cr1 (CR1)"
ip route replace 10.20.2.2/32 encap mpls 200 via 10.0.3.2 dev leri-cr2
echo "  Tunnel2: 10.20.2.2/32 encap mpls 200 → leri-cr2 (CR2)"
ip route replace 10.20.3.2/32 encap mpls 300 via 10.0.5.2 dev leri-cr3
echo "  Tunnel3: 10.20.3.2/32 encap mpls 300 → leri-cr3 (CR3)"

echo ""
echo "=== Transit LSP ==="
ip netns exec CoreRouter1 ip -f mpls route replace 100 as 101 via inet 10.0.2.2 dev cr1-lere
echo "  CR1: swap 100 → 101"
ip netns exec CoreRouter2 ip -f mpls route replace 200 as 201 via inet 10.0.4.2 dev cr2-lere
echo "  CR2: swap 200 → 201"
ip netns exec CoreRouter3 ip -f mpls route replace 300 as 301 via inet 10.0.6.2 dev cr3-lere
echo "  CR3: swap 300 → 301"

echo ""
echo "=== Egress LSP (root ns = LER_Egress) ==="
ip -f mpls route replace 101 via inet 10.20.1.2 dev Ethernet18
echo "  pop 101 → 10.20.1.2 (Rx1, Ethernet18)"
ip -f mpls route replace 201 via inet 10.20.2.2 dev Ethernet20
echo "  pop 201 → 10.20.2.2 (Rx2, Ethernet20)"
ip -f mpls route replace 301 via inet 10.20.3.2 dev Ethernet22
echo "  pop 301 → 10.20.3.2 (Rx3, Ethernet22)"

echo ""
echo "=== MPLS設定確認 ==="
echo "--- root ns (Ingress) ---"
ip route show | grep "encap mpls"
echo "--- CoreRouter1 ---"
ip netns exec CoreRouter1 ip -f mpls route show
echo "--- root ns (Egress) ---"
ip -f mpls route show

echo ""
echo "MPLS LSP設定完了"
echo "疎通確認: sudo ip netns exec Tx1_ns ping -c3 10.20.1.2"
