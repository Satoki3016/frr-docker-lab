#!/bin/bash
# OSPF-SR + DiffServ-TE 物理2スイッチ構成 SW2 セットアップ
# 実行: SW2 上で  sudo bash scripts/physical2_frr_ospfsr_sw2.sh
#
# ポート割り当て (SW2):
#   Eth2 ← SW1:Eth14 : LER_Egress ← CR1/CR2/CR3 共有 (スイッチ間ケーブル1本)
#   Eth3 ↔ Eth4 : LER_Egress ↔ Rx1 (SW2内ループバックケーブル)
#   Eth5 ↔ Eth6 : LER_Egress ↔ Rx2 (SW2内ループバックケーブル)
#   Eth7 ↔ Eth8 : LER_Egress ↔ Rx3 (SW2内ループバックケーブル)
#   ※ Eth0/1は未使用 (物理ケーブルなし)
#
# SW1 の physical2_frr_ospfsr_sw1.sh と並行して実行可能

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lab_config.sh" 2>/dev/null || true

LAB_IMAGE="${LAB_IMAGE:-nicolaka/netshoot}"
FRR_IMAGE="${FRR_IMAGE:-frrouting/frr}"
SRGB_BASE=16000

dc() { docker exec "$1" "${@:2}"; }

# ── 1. 既存コンテナ削除 ───────────────────────────────────────────────────
echo "=== [1] 既存コンテナ削除 ==="
for name in frr-LER_Egress LER_Egress Rx1 Rx2 Rx3; do
    docker rm -f "$name" 2>/dev/null && echo "  [del] $name" || true
done

# ── 2. カーネルモジュール ─────────────────────────────────────────────────
echo ""
echo "=== [2] カーネルモジュール ==="
modprobe mpls_router   2>/dev/null || true
modprobe mpls_iptunnel 2>/dev/null || true
sysctl -qw net.ipv4.ip_forward=1
sysctl -qw net.mpls.platform_labels=65536
echo "  [ok]"

# ── 3. コンテナ起動 ───────────────────────────────────────────────────────
echo ""
echo "=== [3] コンテナ起動 ==="
for name in LER_Egress Rx1 Rx2 Rx3; do
    docker run -d --name "$name" \
        --network none \
        --privileged \
        --cap-add NET_ADMIN \
        --cap-add NET_RAW \
        --cap-add SYS_MODULE \
        "$LAB_IMAGE" sleep infinity
    echo "  [ok] $name"
done

# ── 4. 物理ポート → bridge+veth → コンテナ ───────────────────────────────
echo ""
echo "=== [4] 物理ポート接続 ==="

connect_port() {
    local eth=$1 container=$2 ifname=$3 ip=$4
    local br="br-${eth}" vr="vr-${eth}"
    local vpid; vpid=$(docker inspect --format='{{.State.Pid}}' "$container")

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

    dc "$container" ip link set "$ifname" mtu 1500 up
    dc "$container" ip addr add "$ip" dev "$ifname"
    echo "  $eth → $container/$ifname ($ip)"
}

# SW1 → LER_Egress (inter-switch: 1本クロスケーブル Ethernet2 共有)
# lere-cr1/2/3 を br-xsw ブリッジに集約し Ethernet2 経由で SW1 と接続
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
    dc "$container" ip link set "$ifname" mtu 1500 up
    dc "$container" ip addr add "$ip" dev "$ifname"
    echo "  $br → $container/$ifname ($ip)"
}

add_to_bridge "$BR_XSW" LER_Egress lere-cr1 10.0.2.2/30
add_to_bridge "$BR_XSW" LER_Egress lere-cr2 10.0.4.2/30
add_to_bridge "$BR_XSW" LER_Egress lere-cr3 10.0.6.2/30

# LER_Egress↔Rx vethペア (LER_Egress=.2, Rx=.1 — measure_sw1.shは.1へiperf3接続)
# KNETループバックボトルネックをバイパスするためvethペアで直結
connect_veth_pair() {
    local ca=$1 ifa=$2 ipa=$3 cb=$4 ifb=$5 ipb=$6
    local pid_a; pid_a=$(docker inspect --format='{{.State.Pid}}' "$ca")
    local pid_b; pid_b=$(docker inspect --format='{{.State.Pid}}' "$cb")
    local tmp_a="tmp-${ifa}" tmp_b="tmp-${ifb}"
    ip link del "$tmp_a" 2>/dev/null || true
    ip link add "$tmp_a" mtu 1500 type veth peer name "$tmp_b" mtu 1500
    ip link set "$tmp_a" netns "$pid_a" name "$ifa"
    ip link set "$tmp_b" netns "$pid_b" name "$ifb"
    dc "$ca" ip link set "$ifa" up
    dc "$ca" ip addr add "$ipa" dev "$ifa"
    dc "$cb" ip link set "$ifb" up
    dc "$cb" ip addr add "$ipb" dev "$ifb"
    echo "  veth: $ca/$ifa ($ipa) ↔ $cb/$ifb ($ipb)"
}

connect_veth_pair LER_Egress lere-rx1 10.20.1.2/30  Rx1 rx1-lere 10.20.1.1/30
connect_veth_pair LER_Egress lere-rx2 10.20.2.2/30  Rx2 rx2-lere 10.20.2.1/30
connect_veth_pair LER_Egress lere-rx3 10.20.3.2/30  Rx3 rx3-lere 10.20.3.1/30

# ── 5. ASIC VLAN 設定 ─────────────────────────────────────────────────────
#
# Ethernet3-8 (旧loopback) はvethペアに変更したためASIC設定不要。
# Ethernet2 (inter-switch, SW1:Ethernet14側) のみ VLAN 44 に設定。
echo ""
echo "=== [5] ASIC VLAN設定 (Ethernet2のみ) ==="
bcmcmd "vlan create 44 pbm=xe2,cpu ubm=xe2,cpu" 2>/dev/null || true
bcmcmd "pvlan set xe2 44"
bcmcmd "vlan remove 1 pbm=xe2" 2>/dev/null || true
echo "  Ethernet2 → VLAN 44"

# ── 6. ebtables ARP修正 ───────────────────────────────────────────────────
# vr-lere+ = vr-lere-cr1/2/3 (br-xsw cross-SW側のveth peer)
# vr-Ethernet+ はvethペア化後不要
echo ""
echo "=== [6] ebtables ARP修正 ==="
ebtables -I FORWARD 1 -i 'vr-lere+' -p ARP -j ACCEPT 2>/dev/null || true
ebtables -I FORWARD 2 -o 'vr-lere+' -p ARP -j ACCEPT 2>/dev/null || true
echo "  [ok] ARP ACCEPT rules added (vr-lere+ for br-xsw)"

# ── 7. tc ingress VLAN pop ────────────────────────────────────────────────
# Ethernet3-8はvethペア化後不要。Ethernet2(inter-switch)のみ設定。
echo ""
echo "=== [7] tc ingress VLAN pop (Ethernet2のみ) ==="
tc qdisc del dev "Ethernet2" handle ffff: ingress 2>/dev/null || true
tc qdisc add dev "Ethernet2" handle ffff: ingress
tc filter add dev "Ethernet2" parent ffff: protocol 802.1Q flower vlan_id 44 action vlan pop
echo "  Ethernet2: vlan pop 44"

# ── 8. ループバックIP・MPLS有効化 ─────────────────────────────────────────
echo ""
echo "=== [8] ループバックIP・MPLS有効化 ==="
dc LER_Egress ip addr add 192.168.0.5/32 dev lo
dc LER_Egress ip link set lo up
dc LER_Egress sysctl -qw net.ipv4.ip_forward=1
dc LER_Egress sysctl -qw net.mpls.platform_labels=65536
echo "  [ok] LER_Egress lo=192.168.0.5/32"

for dev in lere-cr1 lere-cr2 lere-cr3; do
    dc LER_Egress sysctl -qw "net.mpls.conf.${dev}.input=1"
done
echo "  [ok] MPLS input enabled (lere-cr1/2/3)"

# ── 9. 静的ルーティング ───────────────────────────────────────────────────
echo ""
echo "=== [9] 静的ルーティング ==="
dc LER_Egress ip route add 10.10.0.0/16 via 10.0.2.1 metric 1
dc LER_Egress ip route add 10.10.0.0/16 via 10.0.4.1 metric 2
dc LER_Egress ip route add 10.10.0.0/16 via 10.0.6.1 metric 3

dc Rx1 ip route add default via 10.20.1.2 dev rx1-lere
dc Rx2 ip route add default via 10.20.2.2 dev rx2-lere
dc Rx3 ip route add default via 10.20.3.2 dev rx3-lere
echo "  [ok]"

# ── 10. FRR OSPF-SR companion コンテナ起動 (LER_Egress) ──────────────────
echo ""
echo "=== [10] FRR OSPF-SR companion コンテナ起動 (LER_Egress) ==="

cfg_dir="/tmp/frr-lab-LER_Egress"
mkdir -p "$cfg_dir"
chmod 777 "$cfg_dir"

cat > "${cfg_dir}/daemons" << 'DAEMONS'
zebra=yes
ospfd=yes
bfdd=yes
staticd=yes
vtysh_enable=yes
DAEMONS

echo "service integrated-vtysh-config" > "${cfg_dir}/vtysh.conf"

cat > "${cfg_dir}/frr.conf" << FRRCONF
frr version 8.4
frr defaults traditional
hostname frr-LER_Egress
log syslog informational
!
interface lere-cr1
 ip ospf network point-to-point
 ip ospf hello-interval 1
 ip ospf dead-interval 3
 ip ospf bfd
!
interface lere-cr2
 ip ospf network point-to-point
 ip ospf hello-interval 1
 ip ospf dead-interval 3
 ip ospf bfd
!
interface lere-cr3
 ip ospf network point-to-point
 ip ospf hello-interval 1
 ip ospf dead-interval 3
 ip ospf bfd
!
bfd
 profile fast
  receive-interval 50
  transmit-interval 50
  detect-multiplier 3
 !
!
router ospf
 ospf router-id 192.168.0.5
 network 10.0.0.0/8 area 0
 network 192.168.0.0/24 area 0
 capability opaque
 mpls-te on
 mpls-te router-address 192.168.0.5
 segment-routing on
 segment-routing global-block ${SRGB_BASE} 23999
 segment-routing node-msd 8
 segment-routing prefix 192.168.0.5/32 index 5 no-php-flag
 fast-reroute ti-lfa
!
FRRCONF
chmod 644 "${cfg_dir}"/*

docker rm -f "frr-LER_Egress" 2>/dev/null || true
docker run -d --name "frr-LER_Egress" \
    --network "container:LER_Egress" \
    --privileged \
    -v "${cfg_dir}:/etc/frr" \
    "$FRR_IMAGE"
echo "  [ok] frr-LER_Egress (router-id=192.168.0.5, label=$(( SRGB_BASE + 5 )))"

# ── 11. DropTail (LER_Egress → Rx) ───────────────────────────────────────
echo ""
echo "=== [11] DropTail (lere-rx1/2/3) ==="
for dev in lere-rx1 lere-rx2 lere-rx3; do
    dc LER_Egress tc qdisc del dev "$dev" root 2>/dev/null || true
    dc LER_Egress tc qdisc add dev "$dev" root handle 1: pfifo limit 100
    echo "  $dev: pfifo 100pkt"
done

# ── 12. OSPF収束確認 ─────────────────────────────────────────────────────
echo ""
echo "=== [12] OSPF収束待ち (20秒) ==="
sleep 20

echo ""
echo "--- OSPF neighbors (LER_Egress) ---"
docker exec frr-LER_Egress vtysh -c "show ip ospf neighbor" 2>/dev/null || echo "  (収束中 — SW1も起動済みか確認)"

echo ""
echo "████████████████████████████████████████"
echo "  SW2 セットアップ完了"
echo "████████████████████████████████████████"
echo ""
echo "■ 状態確認:"
echo "  docker exec frr-LER_Egress vtysh -c 'show ip ospf neighbor'"
echo "  docker exec frr-LER_Egress vtysh -c 'show mpls table'"
echo ""
echo "■ 疎通確認 (SW1側で実行):"
echo "  docker exec Tx1 ping -c3 10.20.1.1   # Tx1 → Rx1"
echo "  docker exec Tx2 ping -c3 10.20.2.1   # Tx2 → Rx2"
echo "  docker exec Tx3 ping -c3 10.20.3.1   # Tx3 → Rx3"
