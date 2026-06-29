#!/bin/bash
# 物理2スイッチ構成 SW1 Docker セットアップ
# 実行: Switch1 上で  sudo bash scripts/physical2_docker_sw1.sh
#
# ポート割り当て（全ポートroot nsに残し bridge+veth でコンテナに接続）:
#   Eth0 ↔ Eth1  : Tx1 ↔ LER_Ingress  (loopback)
#   Eth2 ↔ Eth3  : Tx2 ↔ LER_Ingress  (loopback)
#   Eth4 ↔ Eth5  : Tx3 ↔ LER_Ingress  (loopback)
#   Eth6 ↔ Eth7  : LER_Ingress ↔ CR1  (loopback)
#   Eth8 ↔ Eth9  : LER_Ingress ↔ CR2  (loopback)
#   Eth10↔ Eth11 : LER_Ingress ↔ CR3  (loopback)
#   Eth14 → SW2:Eth0 : CR1/CR2/CR3 共有 → LER_Egress (inter-switch 1本)
#   ※ Eth12/13は未使用
#
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lab_config.sh" 2>/dev/null || true

IMAGE="${LAB_IMAGE:-nicolaka/netshoot}"
CR1_BW="${CR1_BW:-100M}";  CR2_BW="${CR2_BW:-100M}";  CR3_BW="${CR3_BW:-100M}"
WRR_HI="${WRR_HI:-4}"; WRR_ME="${WRR_ME:-2}"; WRR_LO="${WRR_LO:-1}"

# ── 1. コンテナ起動 ───────────────────────────────────────────────
echo "=== [SW1] コンテナ起動 ==="
for name in Tx1 Tx2 Tx3 LER_Ingress CR1 CR2 CR3; do
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

# ── 2. カーネルモジュール（root nsで一度だけ）─────────────────────
echo ""
echo "=== [SW1] カーネルモジュール ==="
modprobe mpls_router   2>/dev/null || true
modprobe mpls_iptunnel 2>/dev/null || true
modprobe xt_DSCP       2>/dev/null || true
modprobe xt_mark       2>/dev/null || true
sysctl -qw net.ipv4.ip_forward=1

# ── 3. 物理ポート → bridge+veth → コンテナ ───────────────────────
echo ""
echo "=== [SW1] 物理ポート接続 ==="

# bridge+veth でコンテナに物理ポートを接続する
# 物理ポートは root ns に残す（SONiC KNET 制約）
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

connect_port Ethernet0  Tx1        tx1-ler   10.10.1.2/30
connect_port Ethernet1  LER_Ingress leri-tx1  10.10.1.1/30
connect_port Ethernet2  Tx2        tx2-ler   10.10.2.2/30
connect_port Ethernet3  LER_Ingress leri-tx2  10.10.2.1/30
connect_port Ethernet4  Tx3        tx3-ler   10.10.3.2/30
connect_port Ethernet5  LER_Ingress leri-tx3  10.10.3.1/30
connect_port Ethernet6  LER_Ingress leri-cr1  10.0.1.1/30
connect_port Ethernet7  CR1        cr1-leri  10.0.1.2/30
connect_port Ethernet8  LER_Ingress leri-cr2  10.0.3.1/30
connect_port Ethernet9  CR2        cr2-leri  10.0.3.2/30
connect_port Ethernet10 LER_Ingress leri-cr3  10.0.5.1/30
connect_port Ethernet11 CR3        cr3-leri  10.0.5.2/30
# CR1/CR2/CR3 egress → br-xsw ブリッジ経由で Ethernet14 に集約
BR_XSW="br-xsw"
ip link del "$BR_XSW" 2>/dev/null || true
ip link add "$BR_XSW" type bridge stp_state 0
ip link set Ethernet14 mtu 1500 up
ip link set Ethernet14 master "$BR_XSW"
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

add_to_bridge "$BR_XSW" CR1 cr1-lere 10.0.2.1/30
add_to_bridge "$BR_XSW" CR2 cr2-lere 10.0.4.1/30
add_to_bridge "$BR_XSW" CR3 cr3-lere 10.0.6.1/30

# ── 4. ASIC設定 (SONiC KNET対応) ────────────────────────────────
#
# SW2と同じ問題: FDB→cpu0パスはLinuxブリッジに届かない。
# loopbackポート(Eth0-11)を各1ポートのみのVLANに隔離。
# inter-switchポート(Eth12-14)も同様にVLAN 42-44に設定。
echo ""
echo "=== [SW1] ASIC per-port VLAN設定 ==="
# loopbackポート Ethernet0-11 → VLAN 30-41
for i in $(seq 0 11); do
    vlan=$((30 + i))
    bcmcmd "vlan create $vlan pbm=xe${i},cpu ubm=xe${i},cpu" 2>/dev/null || true
    bcmcmd "pvlan set xe${i} $vlan"
    bcmcmd "vlan remove 1 pbm=xe${i}" 2>/dev/null || true
    echo "  Ethernet${i} → VLAN ${vlan}"
done
# inter-switchポート Ethernet14 のみ → VLAN 44 (1本クロスケーブル)
bcmcmd "vlan create 44 pbm=xe14,cpu ubm=xe14,cpu" 2>/dev/null || true
bcmcmd "pvlan set xe14 44"
bcmcmd "vlan remove 1 pbm=xe14" 2>/dev/null || true
echo "  Ethernet14 → VLAN 44"

# SONiC ebtablesのARP DROPルールを回避
echo ""
echo "=== [SW1] ebtables ARP修正 ==="
ebtables -I FORWARD 1 -i 'vr-Ethernet+' -p ARP -j ACCEPT 2>/dev/null || true
ebtables -I FORWARD 2 -o 'vr-Ethernet+' -p ARP -j ACCEPT 2>/dev/null || true
ebtables -I FORWARD 3 -i 'vr-cr+' -p ARP -j ACCEPT 2>/dev/null || true
ebtables -I FORWARD 4 -o 'vr-cr+' -p ARP -j ACCEPT 2>/dev/null || true
echo "  [ok] ARP ACCEPT rules added"

# BCM ASICはcpuポートへフレームを届ける際にVLANタグを付加する（ubmにcpuを
# 追加できないハードウェア仕様）。tc ingressでブリッジ処理より前にタグを剥がす。
echo ""
echo "=== [SW1] tc ingress VLAN pop ==="
for i in $(seq 0 11); do
    vlan=$((30 + i))
    tc qdisc del dev "Ethernet${i}" handle ffff: ingress 2>/dev/null || true
    tc qdisc add dev "Ethernet${i}" handle ffff: ingress
    tc filter add dev "Ethernet${i}" parent ffff: protocol 802.1Q flower vlan_id "$vlan" action vlan pop
    echo "  Ethernet${i}: vlan pop $vlan"
done
tc qdisc del dev "Ethernet14" handle ffff: ingress 2>/dev/null || true
tc qdisc add dev "Ethernet14" handle ffff: ingress
tc filter add dev "Ethernet14" parent ffff: protocol 802.1Q flower vlan_id 44 action vlan pop
echo "  Ethernet14: vlan pop 44"

# ── 5. 静的ルーティング ──────────────────────────────────────────
echo ""
echo "=== [SW1] 静的ルーティング ==="
dexec() { docker exec "$@"; }

dexec Tx1 ip route add default via 10.10.1.1
dexec Tx2 ip route add default via 10.10.2.1
dexec Tx3 ip route add default via 10.10.3.1

dexec LER_Ingress ip route add 10.20.1.0/24 via 10.0.1.2 metric 1
dexec LER_Ingress ip route add 10.20.1.0/24 via 10.0.3.2 metric 2
dexec LER_Ingress ip route add 10.20.1.0/24 via 10.0.5.2 metric 3
dexec LER_Ingress ip route add 10.20.2.0/24 via 10.0.3.2 metric 1
dexec LER_Ingress ip route add 10.20.2.0/24 via 10.0.5.2 metric 2
dexec LER_Ingress ip route add 10.20.2.0/24 via 10.0.1.2 metric 3
dexec LER_Ingress ip route add 10.20.3.0/24 via 10.0.5.2 metric 1
dexec LER_Ingress ip route add 10.20.3.0/24 via 10.0.3.2 metric 2
dexec LER_Ingress ip route add 10.20.3.0/24 via 10.0.1.2 metric 3

dexec CR1 ip route add 10.10.0.0/16 via 10.0.1.1
dexec CR1 ip route add 10.20.0.0/16 via 10.0.2.2
dexec CR2 ip route add 10.10.0.0/16 via 10.0.3.1
dexec CR2 ip route add 10.20.0.0/16 via 10.0.4.2
dexec CR3 ip route add 10.10.0.0/16 via 10.0.5.1
dexec CR3 ip route add 10.20.0.0/16 via 10.0.6.2
echo "  [ok]"

# ── 6. MPLS ──────────────────────────────────────────────────────
echo ""
echo "=== [SW1] MPLS ==="
for c in LER_Ingress CR1 CR2 CR3; do
    dexec "$c" sysctl -qw net.mpls.platform_labels=65536
done
for dev in leri-cr1 leri-cr2 leri-cr3; do
    dexec LER_Ingress sysctl -qw "net.mpls.conf.${dev}.input=1"
done
for dev in cr1-leri cr1-lere; do dexec CR1 sysctl -qw "net.mpls.conf.${dev}.input=1"; done
for dev in cr2-leri cr2-lere; do dexec CR2 sysctl -qw "net.mpls.conf.${dev}.input=1"; done
for dev in cr3-leri cr3-lere; do dexec CR3 sysctl -qw "net.mpls.conf.${dev}.input=1"; done

dexec LER_Ingress ip route replace 10.20.1.2/32 encap mpls 100 via 10.0.1.2 dev leri-cr1
dexec LER_Ingress ip route replace 10.20.2.2/32 encap mpls 200 via 10.0.3.2 dev leri-cr2
dexec LER_Ingress ip route replace 10.20.3.2/32 encap mpls 300 via 10.0.5.2 dev leri-cr3

dexec CR1 ip -f mpls route replace 100 as 101 via inet 10.0.2.2 dev cr1-lere
dexec CR2 ip -f mpls route replace 200 as 201 via inet 10.0.4.2 dev cr2-lere
dexec CR3 ip -f mpls route replace 300 as 301 via inet 10.0.6.2 dev cr3-lere
echo "  push: 100/200/300  swap: →101/201/301"

# ── 7. TC (DSCP + WRR HTB + netem) ──────────────────────────────
echo ""
echo "=== [SW1] TC ==="

dexec LER_Ingress iptables -t mangle -F PREROUTING 2>/dev/null || true
dexec LER_Ingress iptables -t mangle -A PREROUTING -p udp --dport 1000 -j DSCP --set-dscp-class AF41
dexec LER_Ingress iptables -t mangle -A PREROUTING -p udp --dport 1000 -j MARK --set-mark 41
dexec LER_Ingress iptables -t mangle -A PREROUTING -p udp --dport 2000 -j DSCP --set-dscp-class AF42
dexec LER_Ingress iptables -t mangle -A PREROUTING -p udp --dport 2000 -j MARK --set-mark 42
dexec LER_Ingress iptables -t mangle -A PREROUTING -p udp --dport 3000 -j DSCP --set-dscp-class AF43
dexec LER_Ingress iptables -t mangle -A PREROUTING -p udp --dport 3000 -j MARK --set-mark 43

rate_to_kbps() {
    local r; r=$(echo "$1" | tr '[:upper:]' '[:lower:]')
    case "$r" in
        *gbit) echo $(( ${r%gbit} * 1000000 )) ;;
        *mbit) echo $(( ${r%mbit} * 1000 )) ;;
        *kbit) echo "${r%kbit}" ;;
        *g)    echo $(( ${r%g}   * 1000000 )) ;;
        *m)    echo $(( ${r%m}   * 1000 )) ;;
        *k)    echo "${r%k}" ;;
        *)     echo 0 ;;
    esac
}
norm_rate() {
    local r; r=$(echo "$1" | tr '[:upper:]' '[:lower:]')
    case "$r" in
        *gbit|*mbit|*kbit) echo "$r" ;;
        *g) echo "${r%g}gbit" ;; *m) echo "${r%m}mbit" ;; *k) echo "${r%k}kbit" ;;
        *) echo "$r" ;;
    esac
}
add_ms() {
    local a b
    a=$(echo "$1" | tr -d 'ms'); a=${a:-0}
    b=$(echo "$2" | tr -d 'ms'); b=${b:-0}
    echo "$(( a + b ))ms"
}

add_wrr_htb() {
    local c=$1 dev=$2 total=$3 r_hi=$4 r_me=$5 r_lo=$6
    local tc_rate; tc_rate=$(norm_rate "$total")
    local tkbps; tkbps=$(rate_to_kbps "$total")
    _b() { local b=$(( $1 * 1000 / 8 / 50 )); echo $(( b < 8192 ? 8192 : b )); }
    local br=$(_b "$tkbps")
    local bh=$(_b "$(rate_to_kbps "$r_hi")")
    local bm=$(_b "$(rate_to_kbps "$r_me")")
    local bl=$(_b "$(rate_to_kbps "$r_lo")")
    local Q_AF41=$(( WRR_HI * 1500 ))
    local Q_AF42=$(( WRR_ME * 1500 ))
    local Q_AF43=$(( WRR_LO * 1500 ))

    dexec "$c" tc qdisc del dev "$dev" root 2>/dev/null || true
    dexec "$c" tc qdisc add dev "$dev" root handle 1: htb default 13
    dexec "$c" tc class add dev "$dev" parent 1:  classid 1:0 htb rate "$tc_rate" ceil "$tc_rate" burst "${br}b" cburst "${br}b"
    # AF41: prio 0 (Strict Priority)
    dexec "$c" tc class add dev "$dev" parent 1:0 classid 1:1 htb rate "$r_hi" ceil "$tc_rate" burst "${bh}b" cburst "${br}b" prio 0 quantum "$Q_AF41"
    # AF42/AF43: prio 1 (WRR) — 同一 prio で quantum 比率 2:1 に従い帯域配分
    dexec "$c" tc class add dev "$dev" parent 1:0 classid 1:2 htb rate "$r_me" ceil "$tc_rate" burst "${bm}b" cburst "${br}b" prio 1 quantum "$Q_AF42"
    dexec "$c" tc class add dev "$dev" parent 1:0 classid 1:3 htb rate "$r_lo" ceil "$tc_rate" burst "${bl}b" cburst "${br}b" prio 1 quantum "$Q_AF43"
    # pfifo リーフ qdisc (netem人工遅延を廃止、自然なキュー遅延で差別化)
    dexec "$c" tc qdisc add dev "$dev" parent 1:1 handle 11: pfifo limit "${PFIFO_LIMIT_HI:-1000}"
    dexec "$c" tc qdisc add dev "$dev" parent 1:2 handle 12: pfifo limit "${PFIFO_LIMIT_ME:-2000}"
    dexec "$c" tc qdisc add dev "$dev" parent 1:3 handle 13: pfifo limit "${PFIFO_LIMIT_LO:-4000}"

    if [ "$c" = "LER_Ingress" ]; then
        dexec "$c" tc filter add dev "$dev" parent 1: protocol all prio 1 handle 41 fw flowid 1:1
        dexec "$c" tc filter add dev "$dev" parent 1: protocol all prio 1 handle 42 fw flowid 1:2
        dexec "$c" tc filter add dev "$dev" parent 1: protocol all prio 1 handle 43 fw flowid 1:3
    else
        dexec "$c" tc filter add dev "$dev" parent 1: protocol 0x8847 prio 1 \
            u32 match u32 0x00880000 0x00FC0000 at 4 flowid 1:1
        dexec "$c" tc filter add dev "$dev" parent 1: protocol 0x8847 prio 1 \
            u32 match u32 0x00900000 0x00FC0000 at 4 flowid 1:2
        dexec "$c" tc filter add dev "$dev" parent 1: protocol 0x8847 prio 1 \
            u32 match u32 0x00980000 0x00FC0000 at 4 flowid 1:3
    fi
}

wrr_subrates() {
    local tkbps; tkbps=$(rate_to_kbps "$1")
    local sum=$(( WRR_HI + WRR_ME + WRR_LO ))
    echo "$(( tkbps * WRR_HI / sum ))kbit $(( tkbps * WRR_ME / sum ))kbit $(( tkbps * WRR_LO / sum ))kbit"
}

read -r cr1_hi cr1_me cr1_lo <<< "$(wrr_subrates "$CR1_BW")"
read -r cr2_hi cr2_me cr2_lo <<< "$(wrr_subrates "$CR2_BW")"
read -r cr3_hi cr3_me cr3_lo <<< "$(wrr_subrates "$CR3_BW")"

add_wrr_htb LER_Ingress leri-cr1 "$CR1_BW" "$cr1_hi" "$cr1_me" "$cr1_lo"
add_wrr_htb LER_Ingress leri-cr2 "$CR2_BW" "$cr2_hi" "$cr2_me" "$cr2_lo"
add_wrr_htb LER_Ingress leri-cr3 "$CR3_BW" "$cr3_hi" "$cr3_me" "$cr3_lo"
add_wrr_htb CR1 cr1-lere "$CR1_BW" "$cr1_hi" "$cr1_me" "$cr1_lo"
add_wrr_htb CR2 cr2-lere "$CR2_BW" "$cr2_hi" "$cr2_me" "$cr2_lo"
add_wrr_htb CR3 cr3-lere "$CR3_BW" "$cr3_hi" "$cr3_me" "$cr3_lo"
echo "  [ok] SP+WRR HTB設定完了"

echo ""
echo "=== [SW1] 完了 ==="
echo "疎通確認: docker exec LER_Ingress ping -c3 10.0.1.2   # LER→CR1"
echo "  ※ SW2セットアップ後: docker exec Tx1 ping -c3 10.20.1.2  # Tx1→Rx1"
