#!/bin/bash
# OSPF-SR + DiffServ-TE 物理2スイッチ構成 SW1 セットアップ
# 実行: SW1 上で  sudo bash scripts/physical2_frr_ospfsr_sw1.sh
#
# ポート割り当て (SW1):
#   Eth0  ↔ Eth1  : Tx1 ↔ LER_Ingress  (SW1内ループバックケーブル)
#   Eth2  ↔ Eth3  : Tx2 ↔ LER_Ingress  (SW1内ループバックケーブル)
#   Eth4  ↔ Eth5  : Tx3 ↔ LER_Ingress  (SW1内ループバックケーブル)
#   Eth6  ↔ Eth7  : LER_Ingress ↔ CR1  (SW1内ループバックケーブル)
#   Eth8  ↔ Eth9  : LER_Ingress ↔ CR2  (SW1内ループバックケーブル)
#   Eth10 ↔ Eth11 : LER_Ingress ↔ CR3  (SW1内ループバックケーブル)
#   Eth14 → SW2:Eth0 : CR1/CR2/CR3 共有egress (スイッチ間ケーブル1本)
#   ※ Eth12/13は未使用 (元3本構成の残ポート)
#
# 前提:
#   - SW2 で physical2_frr_ospfsr_sw2.sh を先に (または並行して) 実行済み
#   - frrouting/frr イメージが docker pull 済み (apt 不要)

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lab_config.sh"

LAB_IMAGE="${LAB_IMAGE:-nicolaka/netshoot}"
FRR_IMAGE="${FRR_IMAGE:-frrouting/frr}"
SRGB_BASE=16000

dc()  { docker exec "$1" "${@:2}"; }

# ── 1. 既存コンテナ削除 ───────────────────────────────────────────────────
echo "=== [1] 既存コンテナ削除 ==="
for name in frr-LER_Ingress frr-CR1 frr-CR2 frr-CR3 \
            LER_Ingress CR1 CR2 CR3 Tx1 Tx2 Tx3; do
    docker rm -f "$name" 2>/dev/null && echo "  [del] $name" || true
done

# ── 2. カーネルモジュール ─────────────────────────────────────────────────
echo ""
echo "=== [2] カーネルモジュール ==="
modprobe mpls_router   2>/dev/null || true
modprobe mpls_iptunnel 2>/dev/null || true
modprobe xt_DSCP       2>/dev/null || true
modprobe xt_mark       2>/dev/null || true
sysctl -qw net.ipv4.ip_forward=1
sysctl -qw net.mpls.platform_labels=65536
echo "  [ok]"

# ── 3. コンテナ起動 ───────────────────────────────────────────────────────
echo ""
echo "=== [3] コンテナ起動 ==="
for name in Tx1 Tx2 Tx3 LER_Ingress CR1 CR2 CR3; do
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
# SONiC KNET制約: 物理ポートはroot nsに残し bridge 経由でコンテナに接続
# br-EthX (bridge) ── EthX (物理) + vr-EthX (root ns veth端) ── ifname (コンテナ内)

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

# Tx ↔ LER_Ingress
connect_port Ethernet0  Tx1         tx1-leri  10.10.1.1/30
connect_port Ethernet1  LER_Ingress leri-tx1  10.10.1.2/30
connect_port Ethernet2  Tx2         tx2-leri  10.10.2.1/30
connect_port Ethernet3  LER_Ingress leri-tx2  10.10.2.2/30
connect_port Ethernet4  Tx3         tx3-leri  10.10.3.1/30
connect_port Ethernet5  LER_Ingress leri-tx3  10.10.3.2/30

# LER_Ingress ↔ CoreRouters
connect_port Ethernet6  LER_Ingress leri-cr1  10.0.1.1/30
connect_port Ethernet7  CR1         cr1-leri  10.0.1.2/30
connect_port Ethernet8  LER_Ingress leri-cr2  10.0.3.1/30
connect_port Ethernet9  CR2         cr2-leri  10.0.3.2/30
connect_port Ethernet10 LER_Ingress leri-cr3  10.0.5.1/30
connect_port Ethernet11 CR3         cr3-leri  10.0.5.2/30

# CoreRouters → SW2 (inter-switch: 1本クロスケーブル Ethernet14 共有)
# CR1/CR2/CR3 の egress を br-xsw ブリッジに集約し Ethernet14 経由で SW2 へ
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
    dc "$container" ip link set "$ifname" mtu 1500 up
    dc "$container" ip addr add "$ip" dev "$ifname"
    echo "  $br → $container/$ifname ($ip)"
}

add_to_bridge "$BR_XSW" CR1 cr1-lere 10.0.2.1/30
add_to_bridge "$BR_XSW" CR2 cr2-lere 10.0.4.1/30
add_to_bridge "$BR_XSW" CR3 cr3-lere 10.0.6.1/30

# ── 5. ASIC per-port VLAN 設定 ────────────────────────────────────────────
echo ""
echo "=== [5] ASIC per-port VLAN設定 ==="
# BCM ASICのFDB→cpu0パスはKNETのper-portフィルタをバイパスするため
# 各ポートを1ポートのみのVLANに隔離してflood→cpu0→KNET経由に強制する

# ループバックポート Ethernet0-11 → VLAN 30-41
for i in $(seq 0 11); do
    vlan=$(( 30 + i ))
    bcmcmd "vlan create $vlan pbm=xe${i},cpu ubm=xe${i},cpu" 2>/dev/null || true
    bcmcmd "pvlan set xe${i} $vlan"
    bcmcmd "vlan remove 1 pbm=xe${i}" 2>/dev/null || true
    echo "  Ethernet${i} → VLAN ${vlan}"
done

# スイッチ間ポート Ethernet14 のみ → VLAN 44 (1本クロスケーブル)
bcmcmd "vlan create 44 pbm=xe14,cpu ubm=xe14,cpu" 2>/dev/null || true
bcmcmd "pvlan set xe14 44"
bcmcmd "vlan remove 1 pbm=xe14" 2>/dev/null || true
echo "  Ethernet14 → VLAN 44"

# ── 6. ebtables ARP修正 ───────────────────────────────────────────────────
echo ""
echo "=== [6] ebtables ARP修正 ==="
ebtables -I FORWARD 1 -i 'vr-Ethernet+' -p ARP -j ACCEPT 2>/dev/null || true
ebtables -I FORWARD 2 -o 'vr-Ethernet+' -p ARP -j ACCEPT 2>/dev/null || true
# 共有ブリッジ側 veth (vr-cr1-lere 等) も許可
ebtables -I FORWARD 3 -i 'vr-cr+' -p ARP -j ACCEPT 2>/dev/null || true
ebtables -I FORWARD 4 -o 'vr-cr+' -p ARP -j ACCEPT 2>/dev/null || true
echo "  [ok]"

# ── 7. tc ingress VLAN pop ────────────────────────────────────────────────
echo ""
echo "=== [7] tc ingress VLAN pop ==="
# BCM ASICはcpuへフレームを届ける際にVLANタグを付加する
# tc ingressでブリッジ処理より前にタグを剥がす

for i in $(seq 0 11); do
    vlan=$(( 30 + i ))
    tc qdisc del dev "Ethernet${i}" handle ffff: ingress 2>/dev/null || true
    tc qdisc add dev "Ethernet${i}" handle ffff: ingress
    tc filter add dev "Ethernet${i}" parent ffff: protocol 802.1Q flower vlan_id "$vlan" action vlan pop
    echo "  Ethernet${i}: vlan pop $vlan"
done
# スイッチ間: Ethernet14 のみ (VLAN 44)
tc qdisc del dev "Ethernet14" handle ffff: ingress 2>/dev/null || true
tc qdisc add dev "Ethernet14" handle ffff: ingress
tc filter add dev "Ethernet14" parent ffff: protocol 802.1Q flower vlan_id 44 action vlan pop
echo "  Ethernet14: vlan pop 44"

# ── 8. ループバックIP・MPLS有効化 ─────────────────────────────────────────
echo ""
echo "=== [8] ループバックIP・MPLS有効化 ==="
declare -A LO_IP=([LER_Ingress]="192.168.0.1" [CR1]="192.168.0.2" [CR2]="192.168.0.3" [CR3]="192.168.0.4")

for cname in LER_Ingress CR1 CR2 CR3; do
    dc "$cname" ip addr add "${LO_IP[$cname]}/32" dev lo
    dc "$cname" ip link set lo up
    dc "$cname" sysctl -qw net.ipv4.ip_forward=1
    dc "$cname" sysctl -qw net.mpls.platform_labels=65536
    echo "  [ok] $cname lo=${LO_IP[$cname]}/32"
done

for iface in leri-cr1 leri-cr2 leri-cr3; do
    dc LER_Ingress sysctl -qw "net.mpls.conf.${iface}.input=1"
done
for dev in cr1-leri cr1-lere; do dc CR1 sysctl -qw "net.mpls.conf.${dev}.input=1"; done
for dev in cr2-leri cr2-lere; do dc CR2 sysctl -qw "net.mpls.conf.${dev}.input=1"; done
for dev in cr3-leri cr3-lere; do dc CR3 sysctl -qw "net.mpls.conf.${dev}.input=1"; done
echo "  [ok] MPLS input enabled"

# ── 9. 静的ルーティング ───────────────────────────────────────────────────
echo ""
echo "=== [9] 静的ルーティング ==="
dc Tx1 ip route add default via 10.10.1.2 dev tx1-leri
dc Tx2 ip route add default via 10.10.2.2 dev tx2-leri
dc Tx3 ip route add default via 10.10.3.2 dev tx3-leri

dc CR1 ip route add 10.10.0.0/16 via 10.0.1.1
dc CR1 ip route add 10.20.0.0/16 via 10.0.2.2
dc CR2 ip route add 10.10.0.0/16 via 10.0.3.1
dc CR2 ip route add 10.20.0.0/16 via 10.0.4.2
dc CR3 ip route add 10.10.0.0/16 via 10.0.5.1
dc CR3 ip route add 10.20.0.0/16 via 10.0.6.2
echo "  [ok]"

# ── 10. FRR OSPF-SR companion コンテナ起動 ──────────────────────────────
echo ""
echo "=== [10] FRR OSPF-SR companion コンテナ起動 ==="

start_frr() {
    local main=$1 router_id=$2 lo_ip=$3 sid_index=$4
    shift 4
    local ospf_ifaces=("$@")
    local cfg_dir="/tmp/frr-lab-${main}"
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

    {
        cat << HEADER
frr version 8.4
frr defaults traditional
hostname frr-${main}
log syslog informational
!
HEADER
        for iface in "${ospf_ifaces[@]}"; do
            cat << IFACE
interface ${iface}
 ip ospf network point-to-point
 ip ospf hello-interval 1
 ip ospf dead-interval 3
 ip ospf bfd
!
IFACE
        done
        cat << BFD
bfd
 profile fast
  receive-interval 50
  transmit-interval 50
  detect-multiplier 3
 !
!
BFD
        cat << OSPF
router ospf
 ospf router-id ${router_id}
 network 10.0.0.0/8 area 0
 network 192.168.0.0/24 area 0
 capability opaque
 mpls-te on
 mpls-te router-address ${lo_ip}
 segment-routing on
 segment-routing global-block ${SRGB_BASE} 23999
 segment-routing node-msd 8
 segment-routing prefix ${lo_ip}/32 index ${sid_index} no-php-flag
 fast-reroute ti-lfa
!
OSPF
    } > "${cfg_dir}/frr.conf"
    chmod 644 "${cfg_dir}"/*

    docker rm -f "frr-${main}" 2>/dev/null || true
    docker run -d --name "frr-${main}" \
        --network "container:${main}" \
        --privileged \
        -v "${cfg_dir}:/etc/frr" \
        "$FRR_IMAGE"
    echo "  [ok] frr-${main} (router-id=${router_id}, label=$(( SRGB_BASE + sid_index )))"
}

start_frr LER_Ingress 192.168.0.1 192.168.0.1 1 leri-cr1 leri-cr2 leri-cr3
start_frr CR1         192.168.0.2 192.168.0.2 2 cr1-leri cr1-lere
start_frr CR2         192.168.0.3 192.168.0.3 3 cr2-leri cr2-lere
start_frr CR3         192.168.0.4 192.168.0.4 4 cr3-leri cr3-lere

# ── 11. OSPF収束待ち ─────────────────────────────────────────────────────
echo ""
echo "=== [11] OSPF収束待ち (30秒) ==="
echo "  ※ SW2 の physical2_frr_ospfsr_sw2.sh が起動済みであること"
sleep 30

echo ""
echo "--- OSPF neighbors (LER_Ingress) ---"
docker exec frr-LER_Ingress vtysh -c "show ip ospf neighbor" 2>/dev/null || echo "  (収束中)"
echo ""
echo "--- SR ラベルテーブル ---"
docker exec frr-LER_Ingress vtysh -c "show mpls table" 2>/dev/null || echo "  (準備中)"

# ── 12. DSCP マーキング + fwmark ─────────────────────────────────────────
echo ""
echo "=== [12] DSCP マーキング + fwmark (LER_Ingress) ==="
dc LER_Ingress iptables -t mangle -F PREROUTING 2>/dev/null || true

dc LER_Ingress iptables -t mangle -A PREROUTING -p udp --dport 1000 -j DSCP --set-dscp-class AF41
dc LER_Ingress iptables -t mangle -A PREROUTING -p udp --dport 2000 -j DSCP --set-dscp-class AF42
dc LER_Ingress iptables -t mangle -A PREROUTING -p udp --dport 3000 -j DSCP --set-dscp-class AF43
dc LER_Ingress iptables -t mangle -A PREROUTING -p udp --dport 5001 -j DSCP --set-dscp-class AF41
dc LER_Ingress iptables -t mangle -A PREROUTING -p udp --dport 5002 -j DSCP --set-dscp-class AF42
dc LER_Ingress iptables -t mangle -A PREROUTING -p udp --dport 5003 -j DSCP --set-dscp-class AF43
dc LER_Ingress iptables -t mangle -A PREROUTING -p icmp -j DSCP --set-dscp-class AF41

dc LER_Ingress iptables -t mangle -A PREROUTING -m dscp --dscp-class AF41 -j MARK --set-mark 41
dc LER_Ingress iptables -t mangle -A PREROUTING -m dscp --dscp-class AF42 -j MARK --set-mark 42
dc LER_Ingress iptables -t mangle -A PREROUTING -m dscp --dscp-class AF43 -j MARK --set-mark 43
echo "  [ok] AF41→mark41 / AF42→mark42 / AF43→mark43"

# ── 13. ポリシールーティングテーブル ─────────────────────────────────────
echo ""
echo "=== [13] ポリシールーティングテーブル (LER_Ingress) ==="
dc LER_Ingress bash -c "
    mkdir -p /etc/iproute2
    grep -q '^41 ' /etc/iproute2/rt_tables 2>/dev/null || echo '41 rt_af41' >> /etc/iproute2/rt_tables
    grep -q '^42 ' /etc/iproute2/rt_tables 2>/dev/null || echo '42 rt_af42' >> /etc/iproute2/rt_tables
    grep -q '^43 ' /etc/iproute2/rt_tables 2>/dev/null || echo '43 rt_af43' >> /etc/iproute2/rt_tables
    ip rule list | grep -E 'fwmark (0x29|0x2a|0x2b)' | cut -d: -f1 | while read prio; do
        ip rule del priority \$prio 2>/dev/null || true
    done
    ip rule add fwmark 41 table 41 priority 100
    ip rule add fwmark 42 table 42 priority 100
    ip rule add fwmark 43 table 43 priority 100
"
echo "  [ok] fwmark 41/42/43 → table 41/42/43"

# ── 14. SR-MPLS 明示経路 ─────────────────────────────────────────────────
echo ""
echo "=== [14] SR-MPLS 明示経路 ==="

# OSPFからLER_Egress SIDを動的取得、失敗時はフォールバック
LERE_LABEL=$(docker exec frr-LER_Ingress vtysh -c "show ip ospf segment-routing" 2>/dev/null \
    | grep "192.168.0.5" | grep -oP '\b1[0-9]{4}\b' | head -1)
LERE_LABEL=${LERE_LABEL:-$(( SRGB_BASE + 5 ))}
echo "  LER_Egress SID: ${LERE_LABEL}"

dc LER_Ingress ip route flush table 41 2>/dev/null || true
dc LER_Ingress ip route flush table 42 2>/dev/null || true
dc LER_Ingress ip route flush table 43 2>/dev/null || true

# 全クラス CR1 主経路 (1リンク3クラス: WRR 4:2:1 が leri-cr1 上で競合)
for tbl in 41 42 43; do
    dc LER_Ingress ip route add table "$tbl" 10.20.0.0/16 \
        encap mpls "${LERE_LABEL}" via 10.0.1.2 dev leri-cr1 metric 1
    dc LER_Ingress ip route add table "$tbl" 10.20.0.0/16 \
        encap mpls "${LERE_LABEL}" via 10.0.3.2 dev leri-cr2 metric 2
done
dc LER_Ingress ip route add table 43 10.20.0.0/16 \
    encap mpls "${LERE_LABEL}" via 10.0.5.2 dev leri-cr3 metric 3
echo "  [ok] table41/42/43: CR1(primary) CR2(fallback) CR3(fallback:43のみ) label=${LERE_LABEL}"

# LER_Egress MPLS入力有効化は SW2 スクリプトで実施

# ── 15. TC/HTB WRR 4:2:1 ─────────────────────────────────────────────────
echo ""
echo "=== [15] TC/HTB WRR (LER_Ingress → CoreRouters) ==="

rate_to_kbps() {
    local r; r=$(echo "$1" | tr '[:upper:]' '[:lower:]')
    case "$r" in
        *gbit|*gbps|*g) echo $(( ${r//[^0-9]/} * 1000000 )) ;;
        *mbit|*mbps|*m) echo $(( ${r//[^0-9]/} * 1000 ))    ;;
        *kbit|*kbps|*k) echo "${r//[^0-9]/}"                ;;
        *) echo 0 ;;
    esac
}
norm_rate() {
    local r; r=$(echo "$1" | tr '[:upper:]' '[:lower:]')
    case "$r" in *mbit) echo "$r";; *mbps) echo "${r%mbps}mbit";; *m) echo "${r%m}mbit";;
        *kbit) echo "$r";; *k) echo "${r%k}kbit";; *g) echo "${r%g}gbit";; *) echo "$r";; esac
}
_b() { local b=$(( $1 * 1000 / 8 / 50 )); echo $(( b < 8192 ? 8192 : b )); }

add_htb_wrr() {
    local cname=$1 dev=$2 total=$3
    local tc_rate; tc_rate=$(norm_rate "$total")
    local tkbps; tkbps=$(rate_to_kbps "$total")
    local sum=$(( WRR_HI + WRR_ME + WRR_LO ))
    local r_hi=$(( tkbps * WRR_HI / sum ))
    local r_me=$(( tkbps * WRR_ME / sum ))
    local r_lo=$(( tkbps * WRR_LO / sum ))

    dc "$cname" tc qdisc del dev "$dev" root 2>/dev/null || true
    dc "$cname" tc qdisc add dev "$dev" root handle 1: htb default 13
    dc "$cname" tc class add dev "$dev" parent 1:  classid 1:0 htb \
        rate "$tc_rate" ceil "$tc_rate" burst "$(_b $tkbps)b" cburst "$(_b $tkbps)b"
    # AF41: prio 0 (Strict Priority)
    dc "$cname" tc class add dev "$dev" parent 1:0 classid 1:1 htb \
        rate "${r_hi}kbit" ceil "$tc_rate" burst "$(_b $r_hi)b" prio 0 quantum $(( WRR_HI * 1500 ))
    # AF42/AF43: prio 1 (WRR) — 同一 prio で quantum 比率 2:1 に従い帯域配分
    dc "$cname" tc class add dev "$dev" parent 1:0 classid 1:2 htb \
        rate "${r_me}kbit" ceil "$tc_rate" burst "$(_b $r_me)b" prio 1 quantum $(( WRR_ME * 1500 ))
    dc "$cname" tc class add dev "$dev" parent 1:0 classid 1:3 htb \
        rate "${r_lo}kbit" ceil "$tc_rate" burst "$(_b $r_lo)b" prio 1 quantum $(( WRR_LO * 1500 ))
    # pfifo リーフ qdisc (netem人工遅延を廃止、自然なキュー遅延で差別化)
    dc "$cname" tc qdisc add dev "$dev" parent 1:1 handle 11: pfifo limit "${PFIFO_LIMIT_HI:-1000}"
    dc "$cname" tc qdisc add dev "$dev" parent 1:2 handle 12: pfifo limit "${PFIFO_LIMIT_ME:-2000}"
    dc "$cname" tc qdisc add dev "$dev" parent 1:3 handle 13: pfifo limit "${PFIFO_LIMIT_LO:-4000}"

    if [ "$cname" = "LER_Ingress" ]; then
        dc "$cname" tc filter add dev "$dev" parent 1: protocol all prio 1 handle 41 fw flowid 1:1
        dc "$cname" tc filter add dev "$dev" parent 1: protocol all prio 1 handle 42 fw flowid 1:2
        dc "$cname" tc filter add dev "$dev" parent 1: protocol all prio 1 handle 43 fw flowid 1:3
    else
        dc "$cname" tc filter add dev "$dev" parent 1: protocol 0x8847 prio 1 \
            u32 match u32 0x00880000 0x00FC0000 at 4 flowid 1:1
        dc "$cname" tc filter add dev "$dev" parent 1: protocol 0x8847 prio 1 \
            u32 match u32 0x00900000 0x00FC0000 at 4 flowid 1:2
        dc "$cname" tc filter add dev "$dev" parent 1: protocol 0x8847 prio 1 \
            u32 match u32 0x00980000 0x00FC0000 at 4 flowid 1:3
    fi
    echo "  [ok] $cname:$dev SP+WRR(${WRR_HI}:${WRR_ME}:${WRR_LO}) ${r_hi}/${r_me}/${r_lo}kbit"
}

add_htb_wrr LER_Ingress leri-cr1 "$CR1_BW"
add_htb_wrr LER_Ingress leri-cr2 "$CR2_BW"
add_htb_wrr LER_Ingress leri-cr3 "$CR3_BW"
add_htb_wrr CR1         cr1-lere "$CR1_BW"
add_htb_wrr CR2         cr2-lere "$CR2_BW"
add_htb_wrr CR3         cr3-lere "$CR3_BW"

# Ingress policing (leri-tx1/2/3)
echo ""
echo "=== [16] Ingress policing (leri-tx1/2/3) ==="
total_kbps=$(( $(rate_to_kbps "$CR1_BW") + $(rate_to_kbps "$CR2_BW") + $(rate_to_kbps "$CR3_BW") ))
sum=$(( WRR_HI + WRR_ME + WRR_LO ))
pb_hi=$(( total_kbps * WRR_HI / sum ))
pb_me=$(( total_kbps * WRR_ME / sum ))
pb_lo=$(( total_kbps * WRR_LO / sum ))
_pb() { local b=$(( $1 * 1000 / 8 / 100 )); echo $(( b < 16384 ? 16384 : b )); }

for pair in "leri-tx1 $pb_hi" "leri-tx2 $pb_me" "leri-tx3 $pb_lo"; do
    dev=${pair% *}; rate=${pair#* }
    dc LER_Ingress tc qdisc del dev "$dev" ingress 2>/dev/null || true
    dc LER_Ingress tc qdisc add dev "$dev" handle ffff: ingress
    dc LER_Ingress tc filter add dev "$dev" parent ffff: protocol all \
        u32 match u32 0 0 police rate "${rate}kbit" burst "$(_pb $rate)b" mtu 9000 drop flowid :1
    echo "  [ok] $dev: police ${rate}kbit"
done

# ── 17. 動的TE経路モニター起動 ────────────────────────────────────────────
echo ""
echo "=== [17] 動的TE経路モニター起動 ==="
pkill -f "frr_te_monitor.sh" 2>/dev/null || true
sleep 0.5
bash "$SCRIPT_DIR/frr_te_monitor.sh" /tmp/frr_te_monitor.log &
sleep 1

echo ""
echo "████████████████████████████████████████"
echo "  SW1 セットアップ完了"
echo "████████████████████████████████████████"
echo ""
echo "■ 状態確認:"
echo "  docker exec frr-LER_Ingress vtysh -c 'show ip ospf neighbor'"
echo "  docker exec frr-LER_Ingress vtysh -c 'show mpls table'"
echo "  docker exec LER_Ingress ip route show table 41"
echo "  tail -f /tmp/frr_te_monitor.log"
echo ""
echo "■ フェイルオーバーテスト:"
echo "  docker exec LER_Ingress ip link set leri-cr1 down  # CR1障害"
echo "  docker exec LER_Ingress ip link set leri-cr1 up    # 復旧"
echo ""
echo "■ 計測:"
echo "  sudo bash scripts/frr_measure.sh 60 physical_normal"
