#!/bin/bash
# SONiC用配線スクリプト
# 物理ポート: SONiC config interface ip add で設定（ASIC プログラミング）
# コアリンク: veth（root namespace ↔ CoreRouter1/2/3 namespace）
set -e

# ── アクセスポートIP設定（SONiC config）───────────────────────
echo "=== SONiC アクセスポートIP設定 ==="
for pair in "Ethernet0:10.10.1.1/30"  "Ethernet2:10.10.2.1/30"  "Ethernet4:10.10.3.1/30" \
            "Ethernet18:10.20.1.1/30" "Ethernet20:10.20.2.1/30" "Ethernet22:10.20.3.1/30"; do
    eth="${pair%%:*}"
    ip="${pair##*:}"
    config interface ip remove "$eth" "$ip" 2>/dev/null || true
    config interface ip add    "$eth" "$ip"
    echo "  [ok] $eth: $ip"
done
sleep 2   # ASIC 反映待ち

# ── veth ペア作成（root ns ↔ CoreRouter namespace）───────────
add_veth() {
    local root_if=$1 root_ip=$2 ns=$3 ns_if=$4 ns_ip=$5
    ip link del "$root_if" 2>/dev/null || true
    ip link add "$root_if" type veth peer name "$ns_if"
    ip addr add "$root_ip" dev "$root_if"
    ip link set "$root_if" up
    ip link set "$ns_if" netns "$ns"
    ip netns exec "$ns" ip addr add "$ns_ip" dev "$ns_if"
    ip netns exec "$ns" ip link set "$ns_if" up
    echo "  [ok] root($root_if $root_ip) <-> $ns($ns_if $ns_ip)"
}

echo ""
echo "=== コアリンク veth ==="
add_veth leri-cr1 10.0.1.1/30 CoreRouter1 cr1-leri 10.0.1.2/30
add_veth leri-cr2 10.0.3.1/30 CoreRouter2 cr2-leri 10.0.3.2/30
add_veth leri-cr3 10.0.5.1/30 CoreRouter3 cr3-leri 10.0.5.2/30
add_veth lere-cr1 10.0.2.2/30 CoreRouter1 cr1-lere 10.0.2.1/30
add_veth lere-cr2 10.0.4.2/30 CoreRouter2 cr2-lere 10.0.4.1/30
add_veth lere-cr3 10.0.6.2/30 CoreRouter3 cr3-lere 10.0.6.1/30

# ── 静的ルーティング ──────────────────────────────────────────
echo ""
echo "=== 静的ルーティング ==="

# root ns (LER_Ingress): Rx宛はCoreRouter経由
ip route add 10.20.1.0/24 via 10.0.1.2 metric 1 2>/dev/null || true
ip route add 10.20.1.0/24 via 10.0.3.2 metric 2 2>/dev/null || true
ip route add 10.20.1.0/24 via 10.0.5.2 metric 3 2>/dev/null || true
ip route add 10.20.2.0/24 via 10.0.3.2 metric 1 2>/dev/null || true
ip route add 10.20.2.0/24 via 10.0.5.2 metric 2 2>/dev/null || true
ip route add 10.20.2.0/24 via 10.0.1.2 metric 3 2>/dev/null || true
ip route add 10.20.3.0/24 via 10.0.5.2 metric 1 2>/dev/null || true
ip route add 10.20.3.0/24 via 10.0.3.2 metric 2 2>/dev/null || true
ip route add 10.20.3.0/24 via 10.0.1.2 metric 3 2>/dev/null || true
echo "  [ok] root ns (Ingress routes)"

ip netns exec CoreRouter1 ip route add 10.10.0.0/16 via 10.0.1.1 metric 1
ip netns exec CoreRouter1 ip route add 10.20.0.0/16 via 10.0.2.2 metric 1
ip netns exec CoreRouter1 ip route add default      via 10.0.2.2 metric 10
echo "  [ok] CoreRouter1"

ip netns exec CoreRouter2 ip route add 10.10.0.0/16 via 10.0.3.1 metric 1
ip netns exec CoreRouter2 ip route add 10.20.0.0/16 via 10.0.4.2 metric 1
ip netns exec CoreRouter2 ip route add default      via 10.0.4.2 metric 10
echo "  [ok] CoreRouter2"

ip netns exec CoreRouter3 ip route add 10.10.0.0/16 via 10.0.5.1 metric 1
ip netns exec CoreRouter3 ip route add 10.20.0.0/16 via 10.0.6.2 metric 1
ip netns exec CoreRouter3 ip route add default      via 10.0.6.2 metric 10
echo "  [ok] CoreRouter3"

# root ns (LER_Egress): Tx宛はCoreRouter経由（return path）
ip route add 10.10.0.0/16 via 10.0.2.1 metric 1 2>/dev/null || true
ip route add 10.10.0.0/16 via 10.0.4.1 metric 2 2>/dev/null || true
ip route add 10.10.0.0/16 via 10.0.6.1 metric 3 2>/dev/null || true
echo "  [ok] root ns (Egress return routes)"

echo ""
echo "Done."
echo "疎通確認: sudo ip netns exec Tx1_ns ping -c3 10.10.1.1"
