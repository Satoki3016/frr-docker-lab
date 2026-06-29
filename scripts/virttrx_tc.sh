#!/bin/bash
# DiffServ QoS - virttrx namespace 版
#
# 30_tc.sh と同一ロジック。インターフェース名・namespace名を virttrx 構成に合わせた変形版:
#   LER_Ingress_ns ingress: enp23s0f1np1(Tx1) / leri-tx2(Tx2) / leri-tx3(Tx3)
#   LER_Ingress_ns egress : leri-cr1 / leri-cr2 / leri-cr3  (変更なし)
#   CoreRouter*_ns egress : cr1-lere / cr2-lere / cr3-lere   (変更なし)
#   LER_Egress_ns  egress : enp5s0f0(Rx1) / lere-rx2(Rx2) / lere-rx3(Rx3)
#
set -e
source "$(dirname "$0")/lab_config.sh"

modprobe xt_DSCP xt_dscp xt_mark 2>/dev/null || true

# ----------------------------------------------------------------
# 帯域計算ヘルパー
# ----------------------------------------------------------------
rate_to_kbps() {
    local r
    r=$(echo "$1" | tr '[:upper:]' '[:lower:]')
    case "$r" in
        *gbit)  echo $(( ${r%gbit}  * 1000000 )) ;;
        *mbit)  echo $(( ${r%mbit}  * 1000 )) ;;
        *kbit)  echo "${r%kbit}" ;;
        *gbps)  echo $(( ${r%gbps}  * 1000000 )) ;;
        *mbps)  echo $(( ${r%mbps}  * 1000 )) ;;
        *kbps)  echo "${r%kbps}" ;;
        *g)     echo $(( ${r%g}     * 1000000 )) ;;
        *m)     echo $(( ${r%m}     * 1000 )) ;;
        *k)     echo "${r%k}" ;;
        *)      echo 0 ;;
    esac
}

normalize_tc_rate() {
    local r
    r=$(echo "$1" | tr '[:upper:]' '[:lower:]')
    case "$r" in
        *gbit|*mbit|*kbit) echo "$r" ;;
        *gbps) echo "${r%gbps}gbit" ;;
        *mbps) echo "${r%mbps}mbit" ;;
        *kbps) echo "${r%kbps}kbit" ;;
        *g)    echo "${r%g}gbit" ;;
        *m)    echo "${r%m}mbit" ;;
        *k)    echo "${r%k}kbit" ;;
        *)     echo "$r" ;;
    esac
}

normalize_tc_delay() { echo "$1" | tr '[:upper:]' '[:lower:]'; }

add_delay_ms() {
    local a b
    a=$(echo "$1" | tr '[:upper:]' '[:lower:]' | sed 's/ms//')
    b=$(echo "$2" | tr '[:upper:]' '[:lower:]' | sed 's/ms//')
    a=${a:-0}; b=${b:-0}
    echo "$(( a + b ))ms"
}

wrr_subrates() {
    local total_kbps
    total_kbps=$(rate_to_kbps "$1")
    local sum=$(( WRR_HI + WRR_ME + WRR_LO ))
    echo "$(( total_kbps * WRR_HI / sum ))kbit $(( total_kbps * WRR_ME / sum ))kbit $(( total_kbps * WRR_LO / sum ))kbit"
}

Q_AF41=$(( WRR_HI * 1400 ))
Q_AF42=$(( WRR_ME * 1400 ))
Q_AF43=$(( WRR_LO * 1400 ))
DROPTAIL_PKTS=100

clear_qdisc() {
    ip netns exec "$1" tc qdisc del dev "$2" root    2>/dev/null || true
    ip netns exec "$1" tc qdisc del dev "$2" ingress 2>/dev/null || true
}

add_droptail() {
    ip netns exec "$1" tc qdisc add dev "$2" root handle 1: pfifo limit $DROPTAIL_PKTS
}

# HTB + WRR + クラス別遅延
add_wrr_htb_dscp() {
    local ns=$1 dev=$2 total_rate=$3 r_hi=$4 r_me=$5 r_lo=$6
    local link_delay=${7:-0ms} extra_me=${8:-0ms} extra_lo=${9:-0ms}
    local tc_rate total_kbps
    tc_rate=$(normalize_tc_rate "$total_rate")
    total_kbps=$(rate_to_kbps "$total_rate")
    _b() { local b=$(( $1 * 1000 / 8 / 50 )); echo $(( b < 8192 ? 8192 : b )); }
    local broot bhi bme blo
    broot=$(_b "$total_kbps")
    bhi=$(_b "$(rate_to_kbps "$r_hi")")
    bme=$(_b "$(rate_to_kbps "$r_me")")
    blo=$(_b "$(rate_to_kbps "$r_lo")")

    local d_hi d_me d_lo
    d_hi=$(normalize_tc_delay "$(add_delay_ms "$link_delay" "0ms")")
    d_me=$(normalize_tc_delay "$(add_delay_ms "$link_delay" "$extra_me")")
    d_lo=$(normalize_tc_delay "$(add_delay_ms "$link_delay" "$extra_lo")")

    ip netns exec "$ns" tc qdisc add dev "$dev" root handle 1: htb default 13
    ip netns exec "$ns" tc class add dev "$dev" parent 1:  classid 1:0 htb rate "$tc_rate" ceil "$tc_rate" burst "${broot}b" cburst "${broot}b"
    ip netns exec "$ns" tc class add dev "$dev" parent 1:0 classid 1:1 htb rate "$r_hi" ceil "$tc_rate" burst "${bhi}b" cburst "${broot}b" prio 0 quantum "$Q_AF41"
    ip netns exec "$ns" tc class add dev "$dev" parent 1:0 classid 1:2 htb rate "$r_me" ceil "$tc_rate" burst "${bme}b" cburst "${broot}b" prio 1 quantum "$Q_AF42"
    ip netns exec "$ns" tc class add dev "$dev" parent 1:0 classid 1:3 htb rate "$r_lo" ceil "$tc_rate" burst "${blo}b" cburst "${broot}b" prio 2 quantum "$Q_AF43"
    ip netns exec "$ns" tc qdisc add dev "$dev" parent 1:1 handle 11: netem delay "$d_hi" limit "$NETEM_LIMIT"
    ip netns exec "$ns" tc qdisc add dev "$dev" parent 1:2 handle 12: netem delay "$d_me" limit "$NETEM_LIMIT"
    ip netns exec "$ns" tc qdisc add dev "$dev" parent 1:3 handle 13: netem delay "$d_lo" limit "$NETEM_LIMIT"

    if [ "$ns" = "LER_Ingress_ns" ]; then
        ip netns exec "$ns" tc filter add dev "$dev" parent 1: protocol all prio 1 handle 41 fw flowid 1:1
        ip netns exec "$ns" tc filter add dev "$dev" parent 1: protocol all prio 1 handle 42 fw flowid 1:2
        ip netns exec "$ns" tc filter add dev "$dev" parent 1: protocol all prio 1 handle 43 fw flowid 1:3
    else
        ip netns exec "$ns" tc filter add dev "$dev" parent 1: protocol 0x8847 prio 1 \
            u32 match u32 0x00880000 0x00FC0000 at 4 flowid 1:1
        ip netns exec "$ns" tc filter add dev "$dev" parent 1: protocol 0x8847 prio 1 \
            u32 match u32 0x00900000 0x00FC0000 at 4 flowid 1:2
        ip netns exec "$ns" tc filter add dev "$dev" parent 1: protocol 0x8847 prio 1 \
            u32 match u32 0x00980000 0x00FC0000 at 4 flowid 1:3
    fi
    ip netns exec "$ns" tc filter add dev "$dev" parent 1: protocol all prio 10 \
        u32 match u32 0 0 flowid 1:3
}

# ----------------------------------------------------------------
# 1. DSCP マーキング (LER_Ingress_ns, iptables mangle PREROUTING)
# ----------------------------------------------------------------
echo "=== DSCP マーキング (LER_Ingress_ns) ==="
ip netns exec LER_Ingress_ns iptables -t mangle -F PREROUTING 2>/dev/null || true

ip netns exec LER_Ingress_ns iptables -t mangle -A PREROUTING \
    -p udp --dport 1000 -j DSCP --set-dscp-class AF41
ip netns exec LER_Ingress_ns iptables -t mangle -A PREROUTING \
    -p udp --dport 2000 -j DSCP --set-dscp-class AF42
ip netns exec LER_Ingress_ns iptables -t mangle -A PREROUTING \
    -p udp --dport 3000 -j DSCP --set-dscp-class AF43
# ICMP (ping) を AF41 として扱う — FIFO 内で iperf3 AF43 より優先
ip netns exec LER_Ingress_ns iptables -t mangle -A PREROUTING \
    -p icmp -j DSCP --set-dscp-class AF41

# fwmark: DSCP → mark (tc filter で参照)
ip netns exec LER_Ingress_ns iptables -t mangle -A PREROUTING \
    -m dscp --dscp-class AF41 -j MARK --set-mark 41
ip netns exec LER_Ingress_ns iptables -t mangle -A PREROUTING \
    -m dscp --dscp-class AF42 -j MARK --set-mark 42
ip netns exec LER_Ingress_ns iptables -t mangle -A PREROUTING \
    -m dscp --dscp-class AF43 -j MARK --set-mark 43

echo "  port 1000 -> DSCP AF41 mark=41"
echo "  port 2000 -> DSCP AF42 mark=42"
echo "  port 3000 -> DSCP AF43 mark=43"
echo "  ICMP(ping) -> DSCP AF41 mark=41 (高優先キューへ)"

# ----------------------------------------------------------------
# 2. WRR 4:2:1 - LER_Ingress_ns egress to CoreRouters
# ----------------------------------------------------------------
echo ""
echo "=== WRR 4:2:1 + 帯域制限 + 遅延 (LER_Ingress_ns → CoreRouters) ==="
echo "  CR1: bw=${CR1_BW} delay=${CR1_DELAY}"
echo "  CR2: bw=${CR2_BW} delay=${CR2_DELAY}"
echo "  CR3: bw=${CR3_BW} delay=${CR3_DELAY}"

read -r cr1_hi cr1_me cr1_lo <<< "$(wrr_subrates "$CR1_BW")"
read -r cr2_hi cr2_me cr2_lo <<< "$(wrr_subrates "$CR2_BW")"
read -r cr3_hi cr3_me cr3_lo <<< "$(wrr_subrates "$CR3_BW")"

clear_qdisc LER_Ingress_ns leri-cr1
add_wrr_htb_dscp LER_Ingress_ns leri-cr1 "$CR1_BW" "$cr1_hi" "$cr1_me" "$cr1_lo" "$CR1_DELAY" "$DELAY_ME" "$DELAY_LO"
echo "  LER_Ingress_ns:leri-cr1  total=${CR1_BW} hi=${cr1_hi} me=${cr1_me} lo=${cr1_lo}"

clear_qdisc LER_Ingress_ns leri-cr2
add_wrr_htb_dscp LER_Ingress_ns leri-cr2 "$CR2_BW" "$cr2_hi" "$cr2_me" "$cr2_lo" "$CR2_DELAY" "$DELAY_ME" "$DELAY_LO"
echo "  LER_Ingress_ns:leri-cr2  total=${CR2_BW} hi=${cr2_hi} me=${cr2_me} lo=${cr2_lo}"

clear_qdisc LER_Ingress_ns leri-cr3
add_wrr_htb_dscp LER_Ingress_ns leri-cr3 "$CR3_BW" "$cr3_hi" "$cr3_me" "$cr3_lo" "$CR3_DELAY" "$DELAY_ME" "$DELAY_LO"
echo "  LER_Ingress_ns:leri-cr3  total=${CR3_BW} hi=${cr3_hi} me=${cr3_me} lo=${cr3_lo}"

# ----------------------------------------------------------------
# 3. WRR 4:2:1 - CoreRouter egress to LER_Egress_ns
# ----------------------------------------------------------------
echo ""
echo "=== WRR 4:2:1 + 帯域制限 + 遅延 (CoreRouters → LER_Egress_ns) ==="

clear_qdisc CoreRouter1_ns cr1-lere
add_wrr_htb_dscp CoreRouter1_ns cr1-lere "$CR1_BW" "$cr1_hi" "$cr1_me" "$cr1_lo" "$CR1_DELAY"
echo "  CoreRouter1_ns:cr1-lere  total=${CR1_BW} delay=${CR1_DELAY}"

clear_qdisc CoreRouter2_ns cr2-lere
add_wrr_htb_dscp CoreRouter2_ns cr2-lere "$CR2_BW" "$cr2_hi" "$cr2_me" "$cr2_lo" "$CR2_DELAY"
echo "  CoreRouter2_ns:cr2-lere  total=${CR2_BW} delay=${CR2_DELAY}"

clear_qdisc CoreRouter3_ns cr3-lere
add_wrr_htb_dscp CoreRouter3_ns cr3-lere "$CR3_BW" "$cr3_hi" "$cr3_me" "$cr3_lo" "$CR3_DELAY"
echo "  CoreRouter3_ns:cr3-lere  total=${CR3_BW} delay=${CR3_DELAY}"

# ----------------------------------------------------------------
# 4. DropTail 100pkt - LER_Egress_ns egress to Rx hosts
# ----------------------------------------------------------------
echo ""
echo "=== DropTail ${DROPTAIL_PKTS}pkt (LER_Egress_ns → Rx) ==="
clear_qdisc LER_Egress_ns lere-rx1
add_droptail   LER_Egress_ns lere-rx1
echo "  LER_Egress_ns:lere-rx1 (Rx1, veth)"

clear_qdisc LER_Egress_ns lere-rx2
add_droptail   LER_Egress_ns lere-rx2
echo "  LER_Egress_ns:lere-rx2 (Rx2, veth)"

clear_qdisc LER_Egress_ns lere-rx3
add_droptail   LER_Egress_ns lere-rx3
echo "  LER_Egress_ns:lere-rx3 (Rx3, veth)"

# ----------------------------------------------------------------
# 5. Ingress policing - LER_Ingress_ns 入力帯域制限 (WRR 4:2:1)
#    物理NIC構成 (virttrx_setup.sh) と全veth構成 (virttrx_setup_allveth.sh) を自動判別
# ----------------------------------------------------------------
echo ""
echo "=== Ingress policing (LER_Ingress_ns, WRR 4:2:1) ==="

# Tx1 LER_Ingress側インターフェース: 物理NICが存在すれば使用、なければveth名にフォールバック
if ip netns exec LER_Ingress_ns ip link show enp23s0f1np1 2>/dev/null | grep -q "enp23s0f1np1"; then
    TX1_IFACE="enp23s0f1np1"
    TX2_IFACE="enp179s0f1np1"
    TX3_IFACE="enp5s0f1"
    echo "  [検出] 物理NIC構成 (enp23s0f1np1 / enp179s0f1np1 / enp5s0f1)"
else
    TX1_IFACE="leri-tx1"
    TX2_IFACE="leri-tx2"
    TX3_IFACE="leri-tx3"
    echo "  [検出] 全veth構成 (leri-tx1 / leri-tx2 / leri-tx3)"
fi

total_bw_kbps=$(( $(rate_to_kbps "$CR1_BW") + $(rate_to_kbps "$CR2_BW") + $(rate_to_kbps "$CR3_BW") ))
total_bw_tc="${total_bw_kbps}kbit"
read -r ingress_hi ingress_me ingress_lo <<< "$(wrr_subrates "$total_bw_tc")"

_pb() { local b=$(( $1 * 1000 / 8 / 100 )); echo $(( b < 16384 ? 16384 : b )); }
pb_hi=$(_pb "$(rate_to_kbps "$ingress_hi")")
pb_me=$(_pb "$(rate_to_kbps "$ingress_me")")
pb_lo=$(_pb "$(rate_to_kbps "$ingress_lo")")

for dev in "$TX1_IFACE" "$TX2_IFACE" "$TX3_IFACE"; do
    ip netns exec LER_Ingress_ns tc qdisc del dev "$dev" ingress 2>/dev/null || true
done

# Tx1 (AF41 高優先)
ip netns exec LER_Ingress_ns tc qdisc add dev "$TX1_IFACE" handle ffff: ingress
ip netns exec LER_Ingress_ns tc filter add dev "$TX1_IFACE" parent ffff: protocol all \
    u32 match u32 0 0 \
    police rate "$ingress_hi" burst "${pb_hi}b" drop flowid :1

# Tx2 (AF42 中優先)
ip netns exec LER_Ingress_ns tc qdisc add dev "$TX2_IFACE" handle ffff: ingress
ip netns exec LER_Ingress_ns tc filter add dev "$TX2_IFACE" parent ffff: protocol all \
    u32 match u32 0 0 \
    police rate "$ingress_me" burst "${pb_me}b" drop flowid :1

# Tx3 (AF43 低優先)
ip netns exec LER_Ingress_ns tc qdisc add dev "$TX3_IFACE" handle ffff: ingress
ip netns exec LER_Ingress_ns tc filter add dev "$TX3_IFACE" parent ffff: protocol all \
    u32 match u32 0 0 \
    police rate "$ingress_lo" burst "${pb_lo}b" drop flowid :1

echo "  総帯域: ${total_bw_tc}"
echo "  ${TX1_IFACE} (Tx1/AF41 高優先): police rate ${ingress_hi} burst ${pb_hi}b"
echo "  ${TX2_IFACE} (Tx2/AF42 中優先): police rate ${ingress_me} burst ${pb_me}b"
echo "  ${TX3_IFACE} (Tx3/AF43 低優先): police rate ${ingress_lo} burst ${pb_lo}b"

echo ""
echo "TC 設定完了"
echo "確認: ip netns exec LER_Ingress_ns tc qdisc show"
