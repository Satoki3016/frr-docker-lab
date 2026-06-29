#!/bin/bash
# DiffServ QoS（SONiC用 - root namespace版）
# LER_Ingress/Egress は root namespace で動作
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lab_config.sh"

/sbin/modprobe xt_DSCP 2>/dev/null || true
/sbin/modprobe xt_mark 2>/dev/null || true

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
normalize_tc_rate() {
    local r; r=$(echo "$1" | tr '[:upper:]' '[:lower:]')
    case "$r" in
        *gbit|*mbit|*kbit) echo "$r" ;;
        *g) echo "${r%g}gbit" ;; *m) echo "${r%m}mbit" ;; *k) echo "${r%k}kbit" ;;
        *)  echo "$r" ;;
    esac
}
add_delay_ms() {
    local a b
    a=$(echo "$1" | tr '[:upper:]' '[:lower:]' | sed 's/ms//'); a=${a:-0}
    b=$(echo "$2" | tr '[:upper:]' '[:lower:]' | sed 's/ms//'); b=${b:-0}
    echo "$(( a + b ))ms"
}
wrr_subrates() {
    local total_kbps; total_kbps=$(rate_to_kbps "$1")
    local sum=$(( WRR_HI + WRR_ME + WRR_LO ))
    echo "$(( total_kbps * WRR_HI / sum ))kbit $(( total_kbps * WRR_ME / sum ))kbit $(( total_kbps * WRR_LO / sum ))kbit"
}

Q_AF41=$(( WRR_HI * 1400 ))
Q_AF42=$(( WRR_ME * 1400 ))
Q_AF43=$(( WRR_LO * 1400 ))
DROPTAIL_PKTS=100

# ns_exec: 空またはroot → そのまま実行、それ以外 → ip netns exec
ns_exec() { local ns=$1; shift; [ -z "$ns" ] && "$@" || ip netns exec "$ns" "$@"; }

clear_qdisc() {
    local ns=$1 dev=$2
    ns_exec "$ns" tc qdisc del dev "$dev" root    2>/dev/null || true
    ns_exec "$ns" tc qdisc del dev "$dev" ingress 2>/dev/null || true
}

add_wrr_htb() {
    local ns=$1 dev=$2 total=$3 r_hi=$4 r_me=$5 r_lo=$6
    local link_delay=${7:-0ms} extra_me=${8:-0ms} extra_lo=${9:-0ms}
    local tc_rate; tc_rate=$(normalize_tc_rate "$total")
    local total_kbps; total_kbps=$(rate_to_kbps "$total")
    _b() { local b=$(( $1 * 1000 / 8 / 50 )); echo $(( b < 8192 ? 8192 : b )); }
    local br=$(_b "$total_kbps")
    local bh=$(_b "$(rate_to_kbps "$r_hi")")
    local bm=$(_b "$(rate_to_kbps "$r_me")")
    local bl=$(_b "$(rate_to_kbps "$r_lo")")
    local d_hi; d_hi=$(add_delay_ms "$link_delay" "0ms")
    local d_me; d_me=$(add_delay_ms "$link_delay" "$extra_me")
    local d_lo; d_lo=$(add_delay_ms "$link_delay" "$extra_lo")

    ns_exec "$ns" tc qdisc add dev "$dev" root handle 1: htb default 13
    ns_exec "$ns" tc class add dev "$dev" parent 1:  classid 1:0 htb rate "$tc_rate" ceil "$tc_rate" burst "${br}b" cburst "${br}b"
    ns_exec "$ns" tc class add dev "$dev" parent 1:0 classid 1:1 htb rate "$r_hi" ceil "$tc_rate" burst "${bh}b" cburst "${br}b" prio 0 quantum "$Q_AF41"
    ns_exec "$ns" tc class add dev "$dev" parent 1:0 classid 1:2 htb rate "$r_me" ceil "$tc_rate" burst "${bm}b" cburst "${br}b" prio 1 quantum "$Q_AF42"
    ns_exec "$ns" tc class add dev "$dev" parent 1:0 classid 1:3 htb rate "$r_lo" ceil "$tc_rate" burst "${bl}b" cburst "${br}b" prio 2 quantum "$Q_AF43"
    ns_exec "$ns" tc qdisc add dev "$dev" parent 1:1 handle 11: netem delay "$d_hi" limit "$NETEM_LIMIT"
    ns_exec "$ns" tc qdisc add dev "$dev" parent 1:2 handle 12: netem delay "$d_me" limit "$NETEM_LIMIT"
    ns_exec "$ns" tc qdisc add dev "$dev" parent 1:3 handle 13: netem delay "$d_lo" limit "$NETEM_LIMIT"

    # root ns (LER_Ingress): fwmark フィルタ
    # CoreRouter ns: MPLS 内 IP TOS フィルタ
    if [ -z "$ns" ]; then
        ns_exec "$ns" tc filter add dev "$dev" parent 1: protocol all prio 1 handle 41 fw flowid 1:1
        ns_exec "$ns" tc filter add dev "$dev" parent 1: protocol all prio 1 handle 42 fw flowid 1:2
        ns_exec "$ns" tc filter add dev "$dev" parent 1: protocol all prio 1 handle 43 fw flowid 1:3
    else
        ns_exec "$ns" tc filter add dev "$dev" parent 1: protocol 0x8847 prio 1 \
            u32 match u32 0x00880000 0x00FC0000 at 4 flowid 1:1
        ns_exec "$ns" tc filter add dev "$dev" parent 1: protocol 0x8847 prio 1 \
            u32 match u32 0x00900000 0x00FC0000 at 4 flowid 1:2
        ns_exec "$ns" tc filter add dev "$dev" parent 1: protocol 0x8847 prio 1 \
            u32 match u32 0x00980000 0x00FC0000 at 4 flowid 1:3
    fi
    ns_exec "$ns" tc filter add dev "$dev" parent 1: protocol all prio 10 u32 match u32 0 0 flowid 1:3
}

# ── 1. DSCP マーキング + fwmark（root namespace）──────────────
echo "=== DSCP マーキング + fwmark (root ns) ==="
iptables -t mangle -F PREROUTING 2>/dev/null || true
iptables -t mangle -A PREROUTING -p udp --dport 1000 -j DSCP --set-dscp-class AF41
iptables -t mangle -A PREROUTING -p udp --dport 1000 -j MARK --set-mark 41
iptables -t mangle -A PREROUTING -p udp --dport 2000 -j DSCP --set-dscp-class AF42
iptables -t mangle -A PREROUTING -p udp --dport 2000 -j MARK --set-mark 42
iptables -t mangle -A PREROUTING -p udp --dport 3000 -j DSCP --set-dscp-class AF43
iptables -t mangle -A PREROUTING -p udp --dport 3000 -j MARK --set-mark 43
echo "  port 1000 → AF41 fwmark=41"
echo "  port 2000 → AF42 fwmark=42"
echo "  port 3000 → AF43 fwmark=43"

# ── 2. WRR HTB（root ns leri-cr1/2/3）───────────────────────
echo ""
echo "=== WRR HTB (root ns: leri-cr1/2/3) ==="
read -r cr1_hi cr1_me cr1_lo <<< "$(wrr_subrates "$CR1_BW")"
read -r cr2_hi cr2_me cr2_lo <<< "$(wrr_subrates "$CR2_BW")"
read -r cr3_hi cr3_me cr3_lo <<< "$(wrr_subrates "$CR3_BW")"

clear_qdisc "" leri-cr1; add_wrr_htb "" leri-cr1 "$CR1_BW" "$cr1_hi" "$cr1_me" "$cr1_lo" "$CR1_DELAY" "$DELAY_ME" "$DELAY_LO"
echo "  leri-cr1: ${CR1_BW} ${CR1_DELAY} (+me=${DELAY_ME} +lo=${DELAY_LO})"
clear_qdisc "" leri-cr2; add_wrr_htb "" leri-cr2 "$CR2_BW" "$cr2_hi" "$cr2_me" "$cr2_lo" "$CR2_DELAY" "$DELAY_ME" "$DELAY_LO"
echo "  leri-cr2: ${CR2_BW} ${CR2_DELAY}"
clear_qdisc "" leri-cr3; add_wrr_htb "" leri-cr3 "$CR3_BW" "$cr3_hi" "$cr3_me" "$cr3_lo" "$CR3_DELAY" "$DELAY_ME" "$DELAY_LO"
echo "  leri-cr3: ${CR3_BW} ${CR3_DELAY}"

# ── 3. WRR HTB（CoreRouter ns cr1/2/3-lere）─────────────────
echo ""
echo "=== WRR HTB (CoreRouter ns: cr-lere) ==="
clear_qdisc CoreRouter1 cr1-lere; add_wrr_htb CoreRouter1 cr1-lere "$CR1_BW" "$cr1_hi" "$cr1_me" "$cr1_lo" "$CR1_DELAY"
echo "  CoreRouter1:cr1-lere: ${CR1_BW} ${CR1_DELAY}"
clear_qdisc CoreRouter2 cr2-lere; add_wrr_htb CoreRouter2 cr2-lere "$CR2_BW" "$cr2_hi" "$cr2_me" "$cr2_lo" "$CR2_DELAY"
echo "  CoreRouter2:cr2-lere: ${CR2_BW} ${CR2_DELAY}"
clear_qdisc CoreRouter3 cr3-lere; add_wrr_htb CoreRouter3 cr3-lere "$CR3_BW" "$cr3_hi" "$cr3_me" "$cr3_lo" "$CR3_DELAY"
echo "  CoreRouter3:cr3-lere: ${CR3_BW} ${CR3_DELAY}"

# ── 4. DropTail（root ns Ethernet18/20/22）───────────────────
echo ""
echo "=== DropTail ${DROPTAIL_PKTS}pkt (root ns: Ethernet18/20/22) ==="
for dev in Ethernet18 Ethernet20 Ethernet22; do
    clear_qdisc "" "$dev"
    tc qdisc add dev "$dev" root handle 1: pfifo limit "$DROPTAIL_PKTS"
    echo "  $dev"
done

# ── 5. Ingress policing（root ns Ethernet0/2/4）──────────────
echo ""
echo "=== Ingress policing (root ns: Ethernet0/2/4) ==="
total_bw_kbps=$(( $(rate_to_kbps "$CR1_BW") + $(rate_to_kbps "$CR2_BW") + $(rate_to_kbps "$CR3_BW") ))
read -r ingress_hi ingress_me ingress_lo <<< "$(wrr_subrates "${total_bw_kbps}kbit")"
_pb() { local b=$(( $1 * 1000 / 8 / 100 )); echo $(( b < 16384 ? 16384 : b )); }
pb_hi=$(_pb "$(rate_to_kbps "$ingress_hi")")
pb_me=$(_pb "$(rate_to_kbps "$ingress_me")")
pb_lo=$(_pb "$(rate_to_kbps "$ingress_lo")")

for dev in Ethernet0 Ethernet2 Ethernet4; do
    tc qdisc del dev "$dev" ingress 2>/dev/null || true
done
tc qdisc add dev Ethernet0 handle ffff: ingress
tc filter add dev Ethernet0 parent ffff: protocol all u32 match u32 0 0 \
    police rate "$ingress_hi" burst "${pb_hi}b" drop flowid :1
tc qdisc add dev Ethernet2 handle ffff: ingress
tc filter add dev Ethernet2 parent ffff: protocol all u32 match u32 0 0 \
    police rate "$ingress_me" burst "${pb_me}b" drop flowid :1
tc qdisc add dev Ethernet4 handle ffff: ingress
tc filter add dev Ethernet4 parent ffff: protocol all u32 match u32 0 0 \
    police rate "$ingress_lo" burst "${pb_lo}b" drop flowid :1
echo "  Ethernet0 (AF41): ${ingress_hi}  Ethernet2 (AF42): ${ingress_me}  Ethernet4 (AF43): ${ingress_lo}"

echo ""
echo "TC 設定完了"
