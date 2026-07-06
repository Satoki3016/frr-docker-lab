#!/bin/bash
# 物理2スイッチ構成 SW2 Docker セットアップ
# 実行: Switch2 上で  sudo bash scripts/physical2_docker_sw2.sh
#
# ポート割り当て:
#   Eth2 ← SW1:Eth14 : LER_Egress ← CR1/CR2/CR3 共有 (inter-switch 1本)
#   Eth3-8 : 旧loopback (現在はvethペアに置き換え済み、ASIC/KNETをバイパス)
#
# IPアドレス割り当て:
#   lere-rx1: 10.20.1.2/30 (LER_Egress側)  rx1-lere: 10.20.1.1/30 (Rx1側)
#   lere-rx2: 10.20.2.2/30 (LER_Egress側)  rx2-lere: 10.20.2.1/30 (Rx2側)
#   lere-rx3: 10.20.3.2/30 (LER_Egress側)  rx3-lere: 10.20.3.1/30 (Rx3側)
#   ※ measure_sw1.sh は 10.20.x.1 (Rx側) へiperf3接続するため Rx=.1 が正しい
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

# ── 3. コンテナ間接続 ────────────────────────────────────────────
#
# LER_Egress↔Rx1/2/3 は物理loopback(Ethernet3-8)経由だと BCM ASIC KNET の
# CPUパス(~38kbps実効)がボトルネックになる。
# kernel vethペアで直結することでKNETを完全バイパスし kernel速度で動作。
# cross-SW link (Ethernet2←SW1:Ethernet14) は引き続き物理ポートを使用。
echo ""
echo "=== [SW2] vethペア接続 (KNET loopbackバイパス) ==="

connect_veth_pair() {
    local ca=$1 ifa=$2 ipa=$3 cb=$4 ifb=$5 ipb=$6
    local pid_a; pid_a=$(docker inspect --format='{{.State.Pid}}' "$ca")
    local pid_b; pid_b=$(docker inspect --format='{{.State.Pid}}' "$cb")
    local tmp_a="tmp-${ifa}" tmp_b="tmp-${ifb}"
    ip link del "$tmp_a" 2>/dev/null || true
    ip link add "$tmp_a" mtu 1500 type veth peer name "$tmp_b" mtu 1500
    ip link set "$tmp_a" netns "$pid_a" name "$ifa"
    ip link set "$tmp_b" netns "$pid_b" name "$ifb"
    docker exec "$ca" ip link set "$ifa" up
    docker exec "$ca" ip addr add "$ipa" dev "$ifa"
    docker exec "$cb" ip link set "$ifb" up
    docker exec "$cb" ip addr add "$ipb" dev "$ifb"
    echo "  veth: $ca/$ifa ($ipa) ↔ $cb/$ifb ($ipb)"
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
# LER_Egress↔Rx vethペア (LER_Egress=.2, Rx=.1 — measure_sw1.shは.1へiperf3接続)
connect_veth_pair LER_Egress lere-rx1 10.20.1.2/30  Rx1 rx1-lere 10.20.1.1/30
connect_veth_pair LER_Egress lere-rx2 10.20.2.2/30  Rx2 rx2-lere 10.20.2.1/30
connect_veth_pair LER_Egress lere-rx3 10.20.3.2/30  Rx3 rx3-lere 10.20.3.1/30

# ── 4. ASIC設定 (SONiC KNET対応) ────────────────────────────────
#
# Ethernet3-8 (旧loopback) はvethペアに変更したためASIC設定不要。
# Ethernet2 (inter-switch, SW1:Eth14側) のみ VLAN 44 に設定。
echo ""
echo "=== [SW2] ASIC VLAN設定 (Ethernet2のみ) ==="
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
# vr-lere+ = vr-lere-cr1/2/3 (br-xsw cross-SW側のveth peer)
# vr-Ethernet+ はvethペア化後不要 (bridge-side veth peer がなくなった)
echo ""
echo "=== [SW2] ebtables ARP修正 ==="
ebtables -I FORWARD 1 -i 'vr-lere+' -p ARP -j ACCEPT 2>/dev/null || true
ebtables -I FORWARD 2 -o 'vr-lere+' -p ARP -j ACCEPT 2>/dev/null || true
echo "  [ok] ARP ACCEPT rules added (vr-lere+ for br-xsw)"

# BCM ASICはcpuポートへフレームを届ける際にVLANタグを付加する（ubmにcpuを
# 追加できないハードウェア仕様）。tc ingressでブリッジ処理より前にタグを剥がす。
# Ethernet3-8はvethペア化後不要。Ethernet2(inter-switch)のみ設定。
echo ""
echo "=== [SW2] tc ingress VLAN pop (Ethernet2のみ) ==="
tc qdisc del dev "Ethernet2" handle ffff: ingress 2>/dev/null || true
tc qdisc add dev "Ethernet2" handle ffff: ingress
tc filter add dev "Ethernet2" parent ffff: protocol 802.1Q flower vlan_id 44 action vlan pop
echo "  Ethernet2: vlan pop 44"

# ── 5. 静的ルーティング ──────────────────────────────────────────
echo ""
echo "=== [SW2] 静的ルーティング ==="
docker exec LER_Egress ip route add 10.10.0.0/16 via 10.0.2.1 metric 1
docker exec LER_Egress ip route add 10.10.0.0/16 via 10.0.4.1 metric 2
docker exec LER_Egress ip route add 10.10.0.0/16 via 10.0.6.1 metric 3

docker exec Rx1 ip route add default via 10.20.1.2
docker exec Rx2 ip route add default via 10.20.2.2
docker exec Rx3 ip route add default via 10.20.3.2
echo "  [ok]"

# ── 6. MPLS (Egress: label pop) ──────────────────────────────────
echo ""
echo "=== [SW2] MPLS ==="
docker exec LER_Egress sysctl -qw net.mpls.platform_labels=65536
for dev in lere-cr1 lere-cr2 lere-cr3; do
    docker exec LER_Egress sysctl -qw "net.mpls.conf.${dev}.input=1"
done

docker exec LER_Egress ip -f mpls route replace 101 via inet 10.20.1.1 dev lere-rx1
docker exec LER_Egress ip -f mpls route replace 201 via inet 10.20.2.1 dev lere-rx2
docker exec LER_Egress ip -f mpls route replace 301 via inet 10.20.3.1 dev lere-rx3
echo "  pop 101→Rx1(10.20.1.1)  201→Rx2(10.20.2.1)  301→Rx3(10.20.3.1)"

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
echo "  docker exec Tx1 ping -c3 10.20.1.1   # Tx1→Rx1"
echo "  docker exec Tx2 ping -c3 10.20.2.1   # Tx2→Rx2"
echo "  docker exec Tx3 ping -c3 10.20.3.1   # Tx3→Rx3"
