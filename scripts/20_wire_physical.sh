#!/bin/bash
# 配線スクリプト（物理ポート + veth ハイブリッド）
#
# アクセスリンク: bridge + veth（SONiC KNET は root ns にのみ配信するため）
#   Ethernet0/2/4   → br-eth0/2/4   → veth → tx1-in/2/3 (LER_Ingress)
#   Ethernet18/20/22 → br-eth18/20/22 → veth → rx1-out/2/3 (LER_Egress)
#
# コアリンク: veth（ASIC を回避）
#   LER_Ingress ↔ CoreRouter1/2/3
#   CoreRouter1/2/3 ↔ LER_Egress
#
set -e
source "$(dirname "$0")/00_env.sh"

# 物理ポートを bridge + veth 経由で namespace に接続
# Ethernet ポートは root ns に残す
# br-ethX (root) ── Ethernet X (root) + vr-ethX (root) ── ns側 ($newname)
assign_port() {
    local ns=$1 eth=$2 newname=$3 ip=$4
    local br="br-${eth,,}"   # e.g., br-ethernet0
    local vr="vr-${eth,,}"   # e.g., vr-ethernet0

    # 既存の bridge/veth をクリーンアップ
    ip link del "$br" 2>/dev/null || true

    # Ethernet ポートを root ns に確保 (MTU 1500)
    ip link set "$eth" mtu 1500 up 2>/dev/null || true

    # bridge 作成（STP 無効 = 即時転送）
    ip link add "$br" type bridge stp_state 0
    ip link set "$eth" master "$br"
    ip link set "$br" mtu 1500 up

    # veth ペア: root 側 ($vr) ↔ namespace 側 ($newname)
    ip link add "$vr" type veth peer name "$newname"
    ip link set "$vr" master "$br"
    ip link set "$vr" mtu 1500 up

    # namespace 側を namespace へ移動して IP 設定
    ip link set "$newname" netns "$ns"
    ip netns exec "$ns" ip addr add "$ip" dev "$newname"
    ip netns exec "$ns" ip link set "$newname" mtu 1500 up

    echo "  [ok] $ns: $eth → $br → $newname ($ip)"
}

# veth ペアを作成してnamespaceに配線
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

# ── アクセスリンク（bridge + veth）────────────────────────────
echo "=== アクセスリンク（bridge + veth）==="
assign_port LER_Ingress Ethernet0  tx1-in  10.10.1.1/30
assign_port LER_Ingress Ethernet2  tx2-in  10.10.2.1/30
assign_port LER_Ingress Ethernet4  tx3-in  10.10.3.1/30
assign_port LER_Egress  Ethernet18 rx1-out 10.20.1.1/30
assign_port LER_Egress  Ethernet20 rx2-out 10.20.2.1/30
assign_port LER_Egress  Ethernet22 rx3-out 10.20.3.1/30

# ── コアリンク（veth）────────────────────────────────────────
echo ""
echo "=== コアリンク（veth）==="
add_veth LER_Ingress leri-cr1 10.0.1.1/30 CoreRouter1 cr1-leri 10.0.1.2/30
add_veth LER_Ingress leri-cr2 10.0.3.1/30 CoreRouter2 cr2-leri 10.0.3.2/30
add_veth LER_Ingress leri-cr3 10.0.5.1/30 CoreRouter3 cr3-leri 10.0.5.2/30
add_veth CoreRouter1 cr1-lere 10.0.2.1/30 LER_Egress  lere-cr1 10.0.2.2/30
add_veth CoreRouter2 cr2-lere 10.0.4.1/30 LER_Egress  lere-cr2 10.0.4.2/30
add_veth CoreRouter3 cr3-lere 10.0.6.1/30 LER_Egress  lere-cr3 10.0.6.2/30

# ── 静的ルーティング ──────────────────────────────────────────
echo ""
echo "=== 静的ルーティング ==="

# LER_Ingress: Rx宛はCoreRouter経由（プライマリ/バックアップ）
ip netns exec LER_Ingress ip route add 10.20.1.0/24 via 10.0.1.2 metric 1
ip netns exec LER_Ingress ip route add 10.20.1.0/24 via 10.0.3.2 metric 2
ip netns exec LER_Ingress ip route add 10.20.1.0/24 via 10.0.5.2 metric 3
ip netns exec LER_Ingress ip route add 10.20.2.0/24 via 10.0.3.2 metric 1
ip netns exec LER_Ingress ip route add 10.20.2.0/24 via 10.0.5.2 metric 2
ip netns exec LER_Ingress ip route add 10.20.2.0/24 via 10.0.1.2 metric 3
ip netns exec LER_Ingress ip route add 10.20.3.0/24 via 10.0.5.2 metric 1
ip netns exec LER_Ingress ip route add 10.20.3.0/24 via 10.0.3.2 metric 2
ip netns exec LER_Ingress ip route add 10.20.3.0/24 via 10.0.1.2 metric 3
echo "  [ok] LER_Ingress"

ip netns exec CoreRouter1 ip route add 10.10.0.0/16 via 10.0.1.1 metric 1
ip netns exec CoreRouter1 ip route add 10.20.0.0/16 via 10.0.2.2 metric 1
ip netns exec CoreRouter1 ip route add default    via 10.0.2.2 metric 10
echo "  [ok] CoreRouter1"

ip netns exec CoreRouter2 ip route add 10.10.0.0/16 via 10.0.3.1 metric 1
ip netns exec CoreRouter2 ip route add 10.20.0.0/16 via 10.0.4.2 metric 1
ip netns exec CoreRouter2 ip route add default    via 10.0.4.2 metric 10
echo "  [ok] CoreRouter2"

ip netns exec CoreRouter3 ip route add 10.10.0.0/16 via 10.0.5.1 metric 1
ip netns exec CoreRouter3 ip route add 10.20.0.0/16 via 10.0.6.2 metric 1
ip netns exec CoreRouter3 ip route add default    via 10.0.6.2 metric 10
echo "  [ok] CoreRouter3"

ip netns exec LER_Egress ip route add 10.10.0.0/16 via 10.0.2.1 metric 1
ip netns exec LER_Egress ip route add 10.10.0.0/16 via 10.0.4.1 metric 2
ip netns exec LER_Egress ip route add 10.10.0.0/16 via 10.0.6.1 metric 3
ip netns exec LER_Egress ip route add default via 10.0.2.1 metric 10
echo "  [ok] LER_Egress"

echo ""
echo "Done."
echo "疎通確認（virttrxから）: ping 10.10.1.1"
