#!/bin/bash
# 物理2スイッチ構成 SW2 Docker セットアップ
# 実行: Switch2 上で  sudo bash scripts/physical2_docker_sw2.sh
#
# ポート割り当て:
#   Eth2 ← SW1:Eth14 : LER_Egress ← CR1/CR2/CR3 共有 (inter-switch 1本)
#   Eth3 ↔ Eth4 : LER_Egress ↔ Rx1 (loopback)
#   Eth5 ↔ Eth6 : LER_Egress ↔ Rx2 (loopback)
#   Eth7 ↔ Eth8 : LER_Egress ↔ Rx3 (loopback)
#   ※ Eth1/2は未使用
#
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${LAB_IMAGE:-nicolaka/netshoot}"

# ── 1. コンテナ起動 ───────────────────────────────────────────────
echo "=== [SW2] コンテナ起動 ==="
for name in LER_Egress Rx1 Rx2 Rx3; do
    docker rm -f "$name" 2>/dev/null || true
    docker run -d --name "$name" \
        --network none \
        --privileged \
        --cap-add NET_ADMIN \
        --cap-add NET_RAW \
        --cap-add SYS_MODULE \
        "$IMAGE" sleep infinity
    echo "  [ok] $name"
done

# ── 2. カーネルモジュール ─────────────────────────────────────────
echo ""
echo "=== [SW2] カーネルモジュール ==="
modprobe mpls_router   2>/dev/null || true
modprobe mpls_iptunnel 2>/dev/null || true
sysctl -qw net.ipv4.ip_forward=1

# ── 3. 物理ポート → bridge+veth → コンテナ ───────────────────────
echo ""
echo "=== [SW2] 物理ポート接続 ==="

connect_port() {
    local eth=$1 container=$2 ifname=$3 ip=$4
    local br="br-${eth}"
    local vr="vr-${eth}"
    local vpid
    vpid=$(docker inspect --format='{{.State.Pid}}' "$container")

    ip link del "$br" 2>/dev/null || true
    ip link add "$br" type bridge stp_state 0
    ip link set "$eth" mtu 1500 up
    ip link set "$eth" master "$br"
    ip link set "$br" mtu 1500 up

    ip link del "$vr" 2>/dev/null || true
    ip link add "$vr" type veth peer name "$ifname"
    ip link set "$vr" master "$br"
    ip link set "$vr" mtu 1500 up
    ip link set "$ifname" netns "$vpid"

    docker exec "$container" ip link set "$ifname" mtu 1500 up
    docker exec "$container" ip addr add "$ip" dev "$ifname"
    echo "  $eth → $container/$ifname ($ip)"
}

# lere-cr1/2/3 を br-xsw ブリッジに集約し Ethernet0 経由で SW1 と接続
BR_XSW="br-xsw"
ip link del "$BR_XSW" 2>/dev/null || true
ip link add "$BR_XSW" type bridge stp_state 0
ip link set Ethernet2 mtu 1500 up
ip link set Ethernet2 master "$BR_XSW"
ip link set "$BR_XSW" mtu 1500 up

add_to_bridge() {
    local br=$1 container=$2 ifname=$3 ip=$4
    local vr="vr-${ifname}"
    local vpid; vpid=$(docker inspect --format='{{.State.Pid}}' "$container")
    ip link del "$vr" 2>/dev/null || true
    ip link add "$vr" type veth peer name "$ifname"
    ip link set "$vr" master "$br"
    ip link set "$vr" mtu 1500 up
    ip link set "$ifname" netns "$vpid"
    docker exec "$container" ip link set "$ifname" mtu 1500 up
    docker exec "$container" ip addr add "$ip" dev "$ifname"
    echo "  $br → $container/$ifname ($ip)"
}

add_to_bridge "$BR_XSW" LER_Egress lere-cr1 10.0.2.2/30
add_to_bridge "$BR_XSW" LER_Egress lere-cr2 10.0.4.2/30
add_to_bridge "$BR_XSW" LER_Egress lere-cr3 10.0.6.2/30
connect_port Ethernet3 LER_Egress lere-rx1  10.20.1.1/30
connect_port Ethernet4 Rx1        rx1-lere  10.20.1.2/30
connect_port Ethernet5 LER_Egress lere-rx2  10.20.2.1/30
connect_port Ethernet6 Rx2        rx2-lere  10.20.2.2/30
connect_port Ethernet7 LER_Egress lere-rx3  10.20.3.1/30
connect_port Ethernet8 Rx3        rx3-lere  10.20.3.2/30

# ── 4. ASIC設定 (SONiC KNET対応) ────────────────────────────────
#
# 問題: SONiC ASICのFDB→cpu0パスはKNETのper-portフィルタをバイパスし
#       Linuxブリッジにフレームが届かない。
# 解決: loopbackポートを各1ポートのみのVLANに隔離する。
#       各VLANにはcpuのみ所属するため全フレームがflood→cpu0→KNET経由
#       で正しくLinuxブリッジに届く（物理ループも防止）。
echo ""
echo "=== [SW2] ASIC per-port VLAN設定 ==="
# loopbackポート Ethernet3-8 → VLAN 20-25
for i in 3 4 5 6 7 8; do
    vlan=$((20 + i - 3))
    bcmcmd "vlan create $vlan pbm=xe${i},cpu ubm=xe${i},cpu" 2>/dev/null || true
    bcmcmd "pvlan set xe${i} $vlan"
    bcmcmd "vlan remove 1 pbm=xe${i}" 2>/dev/null || true
    echo "  Ethernet${i} → VLAN ${vlan}"
done
# inter-switchポート Ethernet2 のみ → VLAN 44 (1本クロスケーブル、SW1側もVLAN44)
bcmcmd "vlan create 44 pbm=xe2,cpu ubm=xe2,cpu" 2>/dev/null || true
bcmcmd "pvlan set xe2 44"
bcmcmd "vlan remove 1 pbm=xe2" 2>/dev/null || true
echo "  Ethernet2 → VLAN 44"
# 誤って追加された静的FDBエントリを削除（あれば）
bcmcmd "l2 show" | grep -v "14:44:8f" | grep "Static" | \
    awk '{print $1}' | sed 's/mac=//' | while read mac; do
    vlan_line=$(bcmcmd "l2 show" | grep "$mac" | grep "vlan=" | head -1)
    vlan=$(echo "$vlan_line" | grep -oP 'vlan=\K[0-9]+')
    [ -n "$vlan" ] && bcmcmd "l2 del mac=$mac vlan=$vlan" 2>/dev/null || true
done

# SONiC ebtablesのARP DROPルールを回避
echo ""
echo "=== [SW2] ebtables ARP修正 ==="
ebtables -I FORWARD 1 -i 'vr-Ethernet+' -p ARP -j ACCEPT 2>/dev/null || true
ebtables -I FORWARD 2 -o 'vr-Ethernet+' -p ARP -j ACCEPT 2>/dev/null || true
ebtables -I FORWARD 3 -i 'vr-lere+' -p ARP -j ACCEPT 2>/dev/null || true
ebtables -I FORWARD 4 -o 'vr-lere+' -p ARP -j ACCEPT 2>/dev/null || true
echo "  [ok] ARP ACCEPT rules added"

# BCM ASICはcpuポートへフレームを届ける際にVLANタグを付加する（ubmにcpuを
# 追加できないハードウェア仕様）。tc ingressでブリッジ処理より前にタグを剥がす。
echo ""
echo "=== [SW2] tc ingress VLAN pop ==="
# スイッチ間: Ethernet2 のみ (VLAN 44)
tc qdisc del dev "Ethernet2" handle ffff: ingress 2>/dev/null || true
tc qdisc add dev "Ethernet2" handle ffff: ingress
tc filter add dev "Ethernet2" parent ffff: protocol 802.1Q flower vlan_id 44 action vlan pop
echo "  Ethernet2: vlan pop 44"
# loopback ports: Ethernet3-8 → VLAN 20-25
for i in 3 4 5 6 7 8; do
    vlan=$((20 + i - 3))
    tc qdisc del dev "Ethernet${i}" handle ffff: ingress 2>/dev/null || true
    tc qdisc add dev "Ethernet${i}" handle ffff: ingress
    tc filter add dev "Ethernet${i}" parent ffff: protocol 802.1Q flower vlan_id "$vlan" action vlan pop
    echo "  Ethernet${i}: vlan pop $vlan"
done

# ── 5. 静的ルーティング ──────────────────────────────────────────
echo ""
echo "=== [SW2] 静的ルーティング ==="
docker exec LER_Egress ip route add 10.10.0.0/16 via 10.0.2.1 metric 1
docker exec LER_Egress ip route add 10.10.0.0/16 via 10.0.4.1 metric 2
docker exec LER_Egress ip route add 10.10.0.0/16 via 10.0.6.1 metric 3

docker exec Rx1 ip route add default via 10.20.1.1
docker exec Rx2 ip route add default via 10.20.2.1
docker exec Rx3 ip route add default via 10.20.3.1
echo "  [ok]"

# ── 6. MPLS (Egress: label pop) ──────────────────────────────────
echo ""
echo "=== [SW2] MPLS ==="
docker exec LER_Egress sysctl -qw net.mpls.platform_labels=65536
for dev in lere-cr1 lere-cr2 lere-cr3; do
    docker exec LER_Egress sysctl -qw "net.mpls.conf.${dev}.input=1"
done

docker exec LER_Egress ip -f mpls route replace 101 via inet 10.20.1.2 dev lere-rx1
docker exec LER_Egress ip -f mpls route replace 201 via inet 10.20.2.2 dev lere-rx2
docker exec LER_Egress ip -f mpls route replace 301 via inet 10.20.3.2 dev lere-rx3
echo "  pop 101→Rx1  201→Rx2  301→Rx3"

# ── 7. DropTail on Egress→Rx ports ───────────────────────────────
echo ""
echo "=== [SW2] DropTail ==="
for dev in lere-rx1 lere-rx2 lere-rx3; do
    docker exec LER_Egress tc qdisc del dev "$dev" root 2>/dev/null || true
    docker exec LER_Egress tc qdisc add dev "$dev" root handle 1: pfifo limit 100
    echo "  $dev: pfifo 100pkt"
done

echo ""
echo "=== [SW2] 完了 ==="
echo "SW1・SW2両方セットアップ後に疎通確認 (SW1側):"
echo "  docker exec Tx1 ping -c3 10.20.1.2   # Tx1→Rx1"
echo "  docker exec Tx2 ping -c3 10.20.2.2   # Tx2→Rx2"
echo "  docker exec Tx3 ping -c3 10.20.3.2   # Tx3→Rx3"
