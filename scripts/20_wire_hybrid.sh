#!/bin/bash
# ハイブリッド配線スクリプト
#
# 物理ポート（SONiC管理, root namespace）+ veth（namespace間）
#
# Tx側:  virttrx → Ethernet0/2/4(root) → veth → LER_Ingress(ns)
# コア:  LER_Ingress(ns) → veth → CoreRouter(ns) → veth → LER_Egress(ns)
# Rx側:  LER_Egress(ns) → veth → Ethernet18/20/22(root) → virttrx
#
# root namespace IPアドレス（SONiC設定済み）:
#   Ethernet0:  10.10.1.2/30  Ethernet2: 10.10.2.2/30  Ethernet4: 10.10.3.2/30
#   Ethernet18: 10.20.1.2/30  Ethernet20: 10.20.2.2/30 Ethernet22: 10.20.3.2/30
#
set -e
source "$(dirname "$0")/00_env.sh"

# root namespaceのIPフォワーディング有効化
sysctl -qw net.ipv4.ip_forward=1
echo "  root namespace: ip_forward=1"

# root ns ↔ namespace間のtransit vethペアを作成
add_transit() {
    local root_if=$1 root_ip=$2 ns=$3 ns_if=$4 ns_ip=$5
    ip link del "$root_if" 2>/dev/null || true
    ip link add "$root_if" type veth peer name "$ns_if"
    ip link set "$ns_if" netns "$ns"
    ip addr add "$root_ip" dev "$root_if"
    ip netns exec "$ns" ip addr add "$ns_ip" dev "$ns_if"
    ip link set "$root_if" up
    ip netns exec "$ns" ip link set "$ns_if" up
    echo "  [ok] root($root_if $root_ip) <-> $ns($ns_if $ns_ip)"
}

# namespace間のvethペアを作成
add_veth() {
    local ns1=$1 if1=$2 ip1=$3 ns2=$4 if2=$5 ip2=$6
    ip netns exec "$ns1" ip link del "$if1" 2>/dev/null || true
    ip netns exec "$ns2" ip link del "$if2" 2>/dev/null || true
    ip link del "$if1" 2>/dev/null || true
    ip link del "$if2" 2>/dev/null || true
    ip link add "$if1" type veth peer name "$if2"
    ip link set "$if1" netns "$ns1"
    ip link set "$if2" netns "$ns2"
    ip netns exec "$ns1" ip addr add "$ip1" dev "$if1"
    ip netns exec "$ns2" ip addr add "$ip2" dev "$if2"
    ip netns exec "$ns1" ip link set "$if1" up
    ip netns exec "$ns2" ip link set "$if2" up
    echo "  [ok] $ns1($if1 $ip1) <-> $ns2($if2 $ip2)"
}

# ── Transit veth: root ns ↔ LER_Ingress ─────────────────────
echo "=== Transit veth (root → LER_Ingress) ==="
add_transit veth-leri-tx1 172.16.1.1/30 LER_Ingress tx1-in 172.16.1.2/30
add_transit veth-leri-tx2 172.16.2.1/30 LER_Ingress tx2-in 172.16.2.2/30
add_transit veth-leri-tx3 172.16.3.1/30 LER_Ingress tx3-in 172.16.3.2/30

# ── Transit veth: root ns ↔ LER_Egress ──────────────────────
echo ""
echo "=== Transit veth (root → LER_Egress) ==="
add_transit veth-lere-rx1 172.16.4.1/30 LER_Egress rx1-out 172.16.4.2/30
add_transit veth-lere-rx2 172.16.5.1/30 LER_Egress rx2-out 172.16.5.2/30
add_transit veth-lere-rx3 172.16.6.1/30 LER_Egress rx3-out 172.16.6.2/30

# ── コアリンク veth ──────────────────────────────────────────
echo ""
echo "=== コアリンク veth ==="
add_veth LER_Ingress leri-cr1 10.0.1.1/30 CoreRouter1 cr1-leri 10.0.1.2/30
add_veth LER_Ingress leri-cr2 10.0.3.1/30 CoreRouter2 cr2-leri 10.0.3.2/30
add_veth LER_Ingress leri-cr3 10.0.5.1/30 CoreRouter3 cr3-leri 10.0.5.2/30
add_veth CoreRouter1 cr1-lere 10.0.2.1/30 LER_Egress lere-cr1 10.0.2.2/30
add_veth CoreRouter2 cr2-lere 10.0.4.1/30 LER_Egress lere-cr2 10.0.4.2/30
add_veth CoreRouter3 cr3-lere 10.0.6.1/30 LER_Egress lere-cr3 10.0.6.2/30

# ── ルーティング設定 ─────────────────────────────────────────
echo ""
echo "=== ルーティング設定 ==="

# root namespace: Tx→Rx トラフィックをLER_Ingressへ転送
ip route replace 10.20.0.0/16 via 172.16.1.2  # Tx1経由（代表）
echo "  root: 10.20.0.0/16 → LER_Ingress(172.16.1.2)"

# root namespace: virttrx Rxサブネットへの戻りルート
# Ethernet18/20/22はSONiCで設定済み（connected route）

# LER_Ingress: 各Rxへのルート（CoreRouter経由）
ip netns exec LER_Ingress ip route add 10.20.1.0/24 via 10.0.1.2 metric 1
ip netns exec LER_Ingress ip route add 10.20.1.0/24 via 10.0.3.2 metric 2
ip netns exec LER_Ingress ip route add 10.20.1.0/24 via 10.0.5.2 metric 3
ip netns exec LER_Ingress ip route add 10.20.2.0/24 via 10.0.3.2 metric 1
ip netns exec LER_Ingress ip route add 10.20.2.0/24 via 10.0.5.2 metric 2
ip netns exec LER_Ingress ip route add 10.20.2.0/24 via 10.0.1.2 metric 3
ip netns exec LER_Ingress ip route add 10.20.3.0/24 via 10.0.5.2 metric 1
ip netns exec LER_Ingress ip route add 10.20.3.0/24 via 10.0.3.2 metric 2
ip netns exec LER_Ingress ip route add 10.20.3.0/24 via 10.0.1.2 metric 3
# Tx subnets: virttrx宛の戻りはroot ns経由
ip netns exec LER_Ingress ip route add 10.10.0.0/16 via 172.16.1.1
echo "  [ok] LER_Ingress"

# CoreRouter1
ip netns exec CoreRouter1 ip route add 10.10.0.0/16 via 10.0.1.1
ip netns exec CoreRouter1 ip route add 10.20.0.0/16 via 10.0.2.2
ip netns exec CoreRouter1 ip route add default via 10.0.2.2 metric 10
echo "  [ok] CoreRouter1"

ip netns exec CoreRouter2 ip route add 10.10.0.0/16 via 10.0.3.1
ip netns exec CoreRouter2 ip route add 10.20.0.0/16 via 10.0.4.2
ip netns exec CoreRouter2 ip route add default via 10.0.4.2 metric 10
echo "  [ok] CoreRouter2"

ip netns exec CoreRouter3 ip route add 10.10.0.0/16 via 10.0.5.1
ip netns exec CoreRouter3 ip route add 10.20.0.0/16 via 10.0.6.2
ip netns exec CoreRouter3 ip route add default via 10.0.6.2 metric 10
echo "  [ok] CoreRouter3"

# LER_Egress: Rxへの出力はroot ns経由（transit veth）
ip netns exec LER_Egress ip route add 10.20.1.0/30 via 172.16.4.1
ip netns exec LER_Egress ip route add 10.20.2.0/30 via 172.16.5.1
ip netns exec LER_Egress ip route add 10.20.3.0/30 via 172.16.6.1
# Txサブネット: CoreRouter経由で戻る
ip netns exec LER_Egress ip route add 10.10.0.0/16 via 10.0.2.1 metric 1
ip netns exec LER_Egress ip route add 10.10.0.0/16 via 10.0.4.1 metric 2
ip netns exec LER_Egress ip route add 10.10.0.0/16 via 10.0.6.1 metric 3
ip netns exec LER_Egress ip route add default via 10.0.2.1 metric 10
echo "  [ok] LER_Egress"

# root namespace: LER_Egressからの戻りパケットをEthernet18/20/22へ
# 10.20.x.0/30はEthernetXのconnected routeとして自動設定済み

echo ""
echo "=== 設定完了 ==="
echo "疎通確認:"
echo "  virttrx: sudo ip route add 10.20.0.0/16 via 10.10.1.2 dev enp23s0f0np0"
echo "  virttrx: ping -I enp23s0f0np0 -c3 10.20.1.1"
