#!/bin/bash
# virttrxをMPLSルーターとして設定するスクリプト（案A: Tx側全て物理）
#
# 物理NIC割り当て（Tx3本 + LER_Ingress3本 → SONiC L2ブリッジ経由）:
#   enp23s0f0np0  → Tx1_ns  (10.10.1.1/30) ─[SONiC VLAN10]─ enp23s0f1np1  → LER_Ingress_ns
#   enp179s0f0np0 → Tx2_ns  (10.10.2.1/30) ─[SONiC VLAN11]─ enp179s0f1np1 → LER_Ingress_ns
#   enp5s0f0      → Tx3_ns  (10.10.3.1/30) ─[SONiC VLAN12]─ enp5s0f1      → LER_Ingress_ns
#
# veth（Rx側・コアリンク全て）:
#   LER_Ingress ↔ CoreRouter1/2/3: veth
#   CoreRouter1/2/3 ↔ LER_Egress: veth
#   LER_Egress ↔ Rx1/2/3: veth

set -e

# ── 既存namespace・IPクリーンアップ ─────────────────────────
echo "=== 既存のnamespaceをクリーンアップ ==="
for ns in Tx1_ns Tx2_ns Tx3_ns Rx1_ns Rx2_ns Rx3_ns LER_Ingress_ns LER_Egress_ns CoreRouter1_ns CoreRouter2_ns CoreRouter3_ns; do
    if ip netns list 2>/dev/null | awk '{print $1}' | grep -qxF "$ns"; then
        for iface in $(ip netns exec "$ns" ip link show 2>/dev/null | grep -E "^[0-9]+" | awk -F': ' '{print $2}' | grep -v lo); do
            ip netns exec "$ns" ip link set "$iface" netns 1 2>/dev/null || true
        done
        ip netns del "$ns"
        echo "  [del] $ns"
    fi
done

for nic in enp23s0f0np0 enp23s0f1np1 enp179s0f0np0 enp179s0f1np1 enp5s0f0 enp5s0f1; do
    ip addr flush dev "$nic" 2>/dev/null || true
done

# ── namespace作成 ─────────────────────────────────────────
echo ""
echo "=== namespace作成 ==="
NODES="Tx1_ns Tx2_ns Tx3_ns LER_Ingress_ns CoreRouter1_ns CoreRouter2_ns CoreRouter3_ns LER_Egress_ns Rx1_ns Rx2_ns Rx3_ns"
for ns in $NODES; do
    ip netns add "$ns"
    ip netns exec "$ns" ip link set lo up
    echo "  [ok] $ns"
done

for ns in LER_Ingress_ns CoreRouter1_ns CoreRouter2_ns CoreRouter3_ns LER_Egress_ns; do
    ip netns exec "$ns" sysctl -qw net.ipv4.ip_forward=1
done

# ── 物理NICをnamespaceに移動（Tx3本 + LER_Ingress3本）──────
echo ""
echo "=== 物理NICをnamespaceに移動 ==="

move_nic() {
    local ns=$1 nic=$2 ip=$3
    ip link set "$nic" down 2>/dev/null || true
    ip link set "$nic" netns "$ns"
    ip netns exec "$ns" ip addr add "$ip" dev "$nic"
    ip netns exec "$ns" ip link set "$nic" up
    echo "  [ok] $ns: $nic ($ip)"
}

move_nic Tx1_ns         enp23s0f0np0   10.10.1.1/30
move_nic LER_Ingress_ns enp23s0f1np1   10.10.1.2/30
move_nic Tx2_ns         enp179s0f0np0  10.10.2.1/30
move_nic LER_Ingress_ns enp179s0f1np1  10.10.2.2/30
move_nic Tx3_ns         enp5s0f0       10.10.3.1/30
move_nic LER_Ingress_ns enp5s0f1       10.10.3.2/30

# ── vethペア作成（Rx側・コアリンク）───────────────────────
echo ""
echo "=== vethペア作成 ==="

add_veth() {
    local ns1=$1 if1=$2 ip1=$3 ns2=$4 if2=$5 ip2=$6
    ip link del "$if1" 2>/dev/null || true
    ip link add "$if1" type veth peer name "$if2"
    ip link set "$if1" netns "$ns1"
    ip link set "$if2" netns "$ns2"
    ip netns exec "$ns1" ip addr add "$ip1" dev "$if1"
    ip netns exec "$ns2" ip addr add "$ip2" dev "$if2"
    ip netns exec "$ns1" ip link set "$if1" up
    ip netns exec "$ns2" ip link set "$if2" up
    echo "  [ok] $ns1($if1 $ip1) <-> $ns2($if2 $ip2)"
}

# LER_Egress → Rx1/2/3 (全て veth)
add_veth LER_Egress_ns lere-rx1 10.20.1.2/30 Rx1_ns rx1-lere 10.20.1.1/30
add_veth LER_Egress_ns lere-rx2 10.20.2.2/30 Rx2_ns rx2-lere 10.20.2.1/30
add_veth LER_Egress_ns lere-rx3 10.20.3.2/30 Rx3_ns rx3-lere 10.20.3.1/30

# コアリンク LER_Ingress ↔ CoreRouters
add_veth LER_Ingress_ns leri-cr1 10.0.1.1/30 CoreRouter1_ns cr1-leri 10.0.1.2/30
add_veth LER_Ingress_ns leri-cr2 10.0.3.1/30 CoreRouter2_ns cr2-leri 10.0.3.2/30
add_veth LER_Ingress_ns leri-cr3 10.0.5.1/30 CoreRouter3_ns cr3-leri 10.0.5.2/30

# コアリンク CoreRouters ↔ LER_Egress
add_veth CoreRouter1_ns cr1-lere 10.0.2.1/30 LER_Egress_ns lere-cr1 10.0.2.2/30
add_veth CoreRouter2_ns cr2-lere 10.0.4.1/30 LER_Egress_ns lere-cr2 10.0.4.2/30
add_veth CoreRouter3_ns cr3-lere 10.0.6.1/30 LER_Egress_ns lere-cr3 10.0.6.2/30

# ── 静的ルーティング ─────────────────────────────────────────
echo ""
echo "=== ルーティング設定 ==="

# Tx hosts: デフォルトゲートウェイ → LER_Ingress
ip netns exec Tx1_ns ip route add default via 10.10.1.2 dev enp23s0f0np0
ip netns exec Tx2_ns ip route add default via 10.10.2.2 dev enp179s0f0np0
ip netns exec Tx3_ns ip route add default via 10.10.3.2 dev enp5s0f0

# Rx hosts: デフォルトゲートウェイ → LER_Egress
ip netns exec Rx1_ns ip route add default via 10.20.1.2 dev rx1-lere
ip netns exec Rx2_ns ip route add default via 10.20.2.2 dev rx2-lere
ip netns exec Rx3_ns ip route add default via 10.20.3.2 dev rx3-lere

# LER_Ingress: Rx宛はCoreRouter経由
ip netns exec LER_Ingress_ns ip route add 10.20.1.0/24 via 10.0.1.2 metric 1
ip netns exec LER_Ingress_ns ip route add 10.20.1.0/24 via 10.0.3.2 metric 2
ip netns exec LER_Ingress_ns ip route add 10.20.1.0/24 via 10.0.5.2 metric 3
ip netns exec LER_Ingress_ns ip route add 10.20.2.0/24 via 10.0.3.2 metric 1
ip netns exec LER_Ingress_ns ip route add 10.20.2.0/24 via 10.0.5.2 metric 2
ip netns exec LER_Ingress_ns ip route add 10.20.2.0/24 via 10.0.1.2 metric 3
ip netns exec LER_Ingress_ns ip route add 10.20.3.0/24 via 10.0.5.2 metric 1
ip netns exec LER_Ingress_ns ip route add 10.20.3.0/24 via 10.0.3.2 metric 2
ip netns exec LER_Ingress_ns ip route add 10.20.3.0/24 via 10.0.1.2 metric 3

# CoreRouters
for i in 1 2 3; do
    ip netns exec "CoreRouter${i}_ns" ip route add 10.10.0.0/16 via "10.0.$((i*2-1)).1"
    ip netns exec "CoreRouter${i}_ns" ip route add 10.20.0.0/16 via "10.0.$((i*2)).2"
done

# LER_Egress: Tx宛はCoreRouter経由（return path）
ip netns exec LER_Egress_ns ip route add 10.10.0.0/16 via 10.0.2.1 metric 1
ip netns exec LER_Egress_ns ip route add 10.10.0.0/16 via 10.0.4.1 metric 2
ip netns exec LER_Egress_ns ip route add 10.10.0.0/16 via 10.0.6.1 metric 3
echo "  [ok] 全ノード"

echo ""
echo "=== 設定完了 ==="
echo "疎通確認: ip netns exec Tx1_ns ping -c3 10.20.1.1"
