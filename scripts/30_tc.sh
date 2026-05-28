#!/bin/bash
# DiffServ QoS - OMNeT++ 設定に対応
#
# 実装内容:
#   1. DSCP マーキング (LER_Ingress ingress, iptables mangle)
#      port 1000 -> AF41 (DSCP=34)  High priority
#      port 2000 -> AF42 (DSCP=36)  Medium priority
#      port 3000 -> AF43 (DSCP=38)  Low priority
#   2. WRR スケジューリング weights=4:2:1 (DRR で近似)
#      LER_Ingress egress: leri-cr1, leri-cr2, leri-cr3
#      CoreRouter  egress: cr1-lere, cr2-lere, cr3-lere
#   3. DropTail 100pkt
#      LER_Egress egress:  lere-rx1, lere-rx2, lere-rx3
#
set -e
source "$(dirname "$0")/00_env.sh"
source "$(dirname "$0")/lab_config.sh"

<<<<<<< HEAD
# iptables モジュール確認 (フルパス: SONiC では /sbin/ がPATHに入らない場合がある)
/sbin/modprobe xt_DSCP 2>/dev/null || true
/sbin/modprobe xt_mark 2>/dev/null || true

=======
>>>>>>> a871d29236fc25033b139708afa500660335c698
# ----------------------------------------------------------------
# WRR 帯域自動計算
#   rate_to_kbps <rate>  → kbps 整数値を出力
#   wrr_subrates <total_rate>  → "hi_kbit me_kbit lo_kbit" を出力 (4:2:1)
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

# tc rate 文字列に正規化 (例: 500M → 500mbit, 1G → 1gbit)
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

# tc delay 文字列に正規化 (例: 2MS → 2ms)
normalize_tc_delay() {
    echo "$1" | tr '[:upper:]' '[:lower:]'
}

# 2つの ms 遅延文字列を加算 (例: "10ms" + "5ms" → "15ms")
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
    local hi=$(( total_kbps * WRR_HI / sum ))
    local me=$(( total_kbps * WRR_ME / sum ))
    local lo=$(( total_kbps * WRR_LO / sum ))
    echo "${hi}kbit ${me}kbit ${lo}kbit"
}

# DSCP 値 (TOS フィールド上位 6bit << 2)
DSCP_AF41=$((34 << 2))   # 0x88 = 136
DSCP_AF42=$((36 << 2))   # 0x90 = 144
DSCP_AF43=$((38 << 2))   # 0x98 = 152
DSCP_MASK=0xfc

# WRR 重み (quantum = weight × 1400byte パケットサイズ)
Q_AF41=$(( WRR_HI * 1400 ))
Q_AF42=$(( WRR_ME * 1400 ))
Q_AF43=$(( WRR_LO * 1400 ))

DROPTAIL_PKTS=100

# ----------------------------------------------------------------
# ヘルパー関数
# ----------------------------------------------------------------

clear_qdisc() {
    local ns=$1 dev=$2
<<<<<<< HEAD
    ip netns exec "$ns" tc qdisc del dev "$dev" root 2>/dev/null || true
    ip netns exec "$ns" tc qdisc del dev "$dev" ingress 2>/dev/null || true
=======
    docker exec "$ns" tc qdisc del dev "$dev" root 2>/dev/null || true
    docker exec "$ns" tc qdisc del dev "$dev" ingress 2>/dev/null || true
>>>>>>> a871d29236fc25033b139708afa500660335c698
}

add_wrr_htb_dscp() {
    # HTB で帯域幅制限 + WRR 4:2:1 + クラス別遅延 を実現
    # フィルタはMPLS内IPヘッダのDSCPバイト(offset=4, mask=0x00FC0000)を直接読む
    # $7 link_delay: リンク共通遅延（例: "10ms"）、省略時は 0ms
    # $8 extra_me:   AF42クラスへの追加遅延 (LER_Ingress のみ有効, 省略=0ms)
    # $9 extra_lo:   AF43クラスへの追加遅延 (LER_Ingress のみ有効, 省略=0ms)
    local ns=$1 dev=$2 total_rate=$3 r_hi=$4 r_me=$5 r_lo=$6
    local link_delay=${7:-0ms} extra_me=${8:-0ms} extra_lo=${9:-0ms}
    local tc_rate total_kbps burst_root burst_hi burst_me burst_lo
    tc_rate=$(normalize_tc_rate "$total_rate")

    # burst = rate[kbps] * 1000 / 8 / 50 (kernel HZ=250 想定, 最小8KB)
    total_kbps=$(rate_to_kbps "$total_rate")
    _b() { local b=$(( $1 * 1000 / 8 / 50 )); echo $(( b < 8192 ? 8192 : b )); }
    burst_root=$(_b "$total_kbps")
    burst_hi=$(_b "$(rate_to_kbps "$r_hi")")
    burst_me=$(_b "$(rate_to_kbps "$r_me")")
    burst_lo=$(_b "$(rate_to_kbps "$r_lo")")

    # クラス別 netem 遅延を計算
<<<<<<< HEAD
=======
    # LER_Ingress: リンク遅延 + クラス固有遅延 (extra_me/extra_lo)
    # CoreRouter:  リンク遅延のみ (extra_me/extra_lo は 0ms のまま)
>>>>>>> a871d29236fc25033b139708afa500660335c698
    local d_hi d_me d_lo
    d_hi=$(normalize_tc_delay "$(add_delay_ms "$link_delay" "0ms")")
    d_me=$(normalize_tc_delay "$(add_delay_ms "$link_delay" "$extra_me")")
    d_lo=$(normalize_tc_delay "$(add_delay_ms "$link_delay" "$extra_lo")")

<<<<<<< HEAD
    ip netns exec "$ns" tc qdisc add dev "$dev" root handle 1: htb default 13
    ip netns exec "$ns" tc class add dev "$dev" parent 1:  classid 1:0 htb rate "$tc_rate" ceil "$tc_rate" burst "${burst_root}b" cburst "${burst_root}b"
    ip netns exec "$ns" tc class add dev "$dev" parent 1:0 classid 1:1 htb rate "$r_hi" ceil "$tc_rate" burst "${burst_hi}b" cburst "${burst_root}b" prio 0 quantum "$Q_AF41"
    ip netns exec "$ns" tc class add dev "$dev" parent 1:0 classid 1:2 htb rate "$r_me" ceil "$tc_rate" burst "${burst_me}b" cburst "${burst_root}b" prio 1 quantum "$Q_AF42"
    ip netns exec "$ns" tc class add dev "$dev" parent 1:0 classid 1:3 htb rate "$r_lo" ceil "$tc_rate" burst "${burst_lo}b" cburst "${burst_root}b" prio 2 quantum "$Q_AF43"
    # リーフ qdisc: netem でクラス別遅延付与 (0ms でも netem を使用し一貫性を保つ)
    ip netns exec "$ns" tc qdisc add dev "$dev" parent 1:1 handle 11: netem delay "$d_hi" limit "$NETEM_LIMIT"
    ip netns exec "$ns" tc qdisc add dev "$dev" parent 1:2 handle 12: netem delay "$d_me" limit "$NETEM_LIMIT"
    ip netns exec "$ns" tc qdisc add dev "$dev" parent 1:3 handle 13: netem delay "$d_lo" limit "$NETEM_LIMIT"
    if [ "$ns" = "LER_Ingress" ]; then
        # LER_Ingress では iptables で付与した fwmark を利用
        ip netns exec "$ns" tc filter add dev "$dev" parent 1: protocol all prio 1 handle 41 fw flowid 1:1
        ip netns exec "$ns" tc filter add dev "$dev" parent 1: protocol all prio 1 handle 42 fw flowid 1:2
        ip netns exec "$ns" tc filter add dev "$dev" parent 1: protocol all prio 1 handle 43 fw flowid 1:3
    else
        # CoreRouter: MPLS内IPのTOS(u32 at 4) でクラス分け
        ip netns exec "$ns" tc filter add dev "$dev" parent 1: protocol 0x8847 prio 1 \
            u32 match u32 0x00880000 0x00FC0000 at 4 flowid 1:1   # DSCP AF41
        ip netns exec "$ns" tc filter add dev "$dev" parent 1: protocol 0x8847 prio 1 \
            u32 match u32 0x00900000 0x00FC0000 at 4 flowid 1:2   # DSCP AF42
        ip netns exec "$ns" tc filter add dev "$dev" parent 1: protocol 0x8847 prio 1 \
            u32 match u32 0x00980000 0x00FC0000 at 4 flowid 1:3   # DSCP AF43
    fi
    ip netns exec "$ns" tc filter add dev "$dev" parent 1: protocol all prio 10 \
=======
    docker exec "$ns" tc qdisc add dev "$dev" root handle 1: htb default 13
    docker exec "$ns" tc class add dev "$dev" parent 1:  classid 1:0 htb rate "$tc_rate" ceil "$tc_rate" burst "${burst_root}b" cburst "${burst_root}b"
    docker exec "$ns" tc class add dev "$dev" parent 1:0 classid 1:1 htb rate "$r_hi" ceil "$tc_rate" burst "${burst_hi}b" cburst "${burst_root}b" prio 0 quantum "$Q_AF41"
    docker exec "$ns" tc class add dev "$dev" parent 1:0 classid 1:2 htb rate "$r_me" ceil "$tc_rate" burst "${burst_me}b" cburst "${burst_root}b" prio 1 quantum "$Q_AF42"
    docker exec "$ns" tc class add dev "$dev" parent 1:0 classid 1:3 htb rate "$r_lo" ceil "$tc_rate" burst "${burst_lo}b" cburst "${burst_root}b" prio 2 quantum "$Q_AF43"
    # リーフ qdisc: netem でクラス別遅延付与 (0ms でも netem を使用し一貫性を保つ)
    docker exec "$ns" tc qdisc add dev "$dev" parent 1:1 handle 11: netem delay "$d_hi" limit "$NETEM_LIMIT"
    docker exec "$ns" tc qdisc add dev "$dev" parent 1:2 handle 12: netem delay "$d_me" limit "$NETEM_LIMIT"
    docker exec "$ns" tc qdisc add dev "$dev" parent 1:3 handle 13: netem delay "$d_lo" limit "$NETEM_LIMIT"
    if [ "$ns" = "LER_Ingress" ]; then
        # LER_Ingress では iptables で付与した fwmark を利用
        docker exec "$ns" tc filter add dev "$dev" parent 1: protocol all prio 1 handle 41 fw flowid 1:1
        docker exec "$ns" tc filter add dev "$dev" parent 1: protocol all prio 1 handle 42 fw flowid 1:2
        docker exec "$ns" tc filter add dev "$dev" parent 1: protocol all prio 1 handle 43 fw flowid 1:3
    else
        # CoreRouter: MPLS内IPのTOS(u32 at 4) でクラス分け
        docker exec "$ns" tc filter add dev "$dev" parent 1: protocol 0x8847 prio 1 \
            u32 match u32 0x00880000 0x00FC0000 at 4 flowid 1:1   # DSCP AF41
        docker exec "$ns" tc filter add dev "$dev" parent 1: protocol 0x8847 prio 1 \
            u32 match u32 0x00900000 0x00FC0000 at 4 flowid 1:2   # DSCP AF42
        docker exec "$ns" tc filter add dev "$dev" parent 1: protocol 0x8847 prio 1 \
            u32 match u32 0x00980000 0x00FC0000 at 4 flowid 1:3   # DSCP AF43
    fi
    docker exec "$ns" tc filter add dev "$dev" parent 1: protocol all prio 10 \
>>>>>>> a871d29236fc25033b139708afa500660335c698
        u32 match u32 0 0 flowid 1:3
}

add_droptail() {
    local ns=$1 dev=$2
<<<<<<< HEAD
    ip netns exec "$ns" tc qdisc add dev "$dev" root handle 1: pfifo limit $DROPTAIL_PKTS
=======
    docker exec "$ns" tc qdisc add dev "$dev" root handle 1: pfifo limit $DROPTAIL_PKTS
>>>>>>> a871d29236fc25033b139708afa500660335c698
}

# ----------------------------------------------------------------
# 1. DSCP マーキング (LER_Ingress, iptables mangle PREROUTING)
# ----------------------------------------------------------------
echo "=== DSCP マーキング (LER_Ingress) ==="
<<<<<<< HEAD
ip netns exec LER_Ingress iptables -t mangle -F PREROUTING 2>/dev/null || true

ip netns exec LER_Ingress iptables -t mangle -A PREROUTING \
    -p udp --dport 1000 -j DSCP --set-dscp-class AF41
ip netns exec LER_Ingress iptables -t mangle -A PREROUTING \
    -p udp --dport 2000 -j DSCP --set-dscp-class AF42
ip netns exec LER_Ingress iptables -t mangle -A PREROUTING \
    -p udp --dport 3000 -j DSCP --set-dscp-class AF43

ip netns exec LER_Ingress iptables -t mangle -A PREROUTING \
    -m dscp --dscp-class AF41 -j MARK --set-mark 41
ip netns exec LER_Ingress iptables -t mangle -A PREROUTING \
    -m dscp --dscp-class AF42 -j MARK --set-mark 42
ip netns exec LER_Ingress iptables -t mangle -A PREROUTING \
    -m dscp --dscp-class AF43 -j MARK --set-mark 43

echo "  port 1000 -> DSCP AF41 (TOS=0x88) fwmark=41"
echo "  port 2000 -> DSCP AF42 (TOS=0x90) fwmark=42"
echo "  port 3000 -> DSCP AF43 (TOS=0x98) fwmark=43"
=======
# DSCPをIPヘッダTOSバイトにセット
# tcフィルタがこのTOSバイトを直接読んでHTBクラスに振り分ける
docker exec LER_Ingress iptables -t mangle -F PREROUTING 2>/dev/null || true

docker exec LER_Ingress iptables -t mangle -A PREROUTING \
    -p udp --dport 1000 -j DSCP --set-dscp-class AF41
docker exec LER_Ingress iptables -t mangle -A PREROUTING \
    -p udp --dport 2000 -j DSCP --set-dscp-class AF42
docker exec LER_Ingress iptables -t mangle -A PREROUTING \
    -p udp --dport 3000 -j DSCP --set-dscp-class AF43

echo "  port 1000 -> DSCP AF41 (TOS=0x88)"
echo "  port 2000 -> DSCP AF42 (TOS=0x90)"
echo "  port 3000 -> DSCP AF43 (TOS=0x98)"
>>>>>>> a871d29236fc25033b139708afa500660335c698

# ----------------------------------------------------------------
# 2. WRR (DRR 4:2:1) - LER_Ingress egress to CoreRouters
# ----------------------------------------------------------------
echo ""
echo "=== WRR 4:2:1 + 帯域制限 + 遅延 (パターンA: 高優先=高帯域・低遅延) ==="
echo "  CR1: bw=${CR1_BW} delay=${CR1_DELAY}"
echo "  CR2: bw=${CR2_BW} delay=${CR2_DELAY}"
echo "  CR3: bw=${CR3_BW} delay=${CR3_DELAY}"

read -r cr1_hi cr1_me cr1_lo <<< "$(wrr_subrates "$CR1_BW")"
read -r cr2_hi cr2_me cr2_lo <<< "$(wrr_subrates "$CR2_BW")"
read -r cr3_hi cr3_me cr3_lo <<< "$(wrr_subrates "$CR3_BW")"

clear_qdisc LER_Ingress leri-cr1
add_wrr_htb_dscp LER_Ingress leri-cr1 "$CR1_BW" "$cr1_hi" "$cr1_me" "$cr1_lo" "$CR1_DELAY" "$DELAY_ME" "$DELAY_LO"
echo "  LER_Ingress:leri-cr1  total=${CR1_BW} hi=${cr1_hi} me=${cr1_me} lo=${cr1_lo} delay=${CR1_DELAY} (+me=${DELAY_ME} +lo=${DELAY_LO})"

clear_qdisc LER_Ingress leri-cr2
add_wrr_htb_dscp LER_Ingress leri-cr2 "$CR2_BW" "$cr2_hi" "$cr2_me" "$cr2_lo" "$CR2_DELAY" "$DELAY_ME" "$DELAY_LO"
echo "  LER_Ingress:leri-cr2  total=${CR2_BW} hi=${cr2_hi} me=${cr2_me} lo=${cr2_lo} delay=${CR2_DELAY} (+me=${DELAY_ME} +lo=${DELAY_LO})"

clear_qdisc LER_Ingress leri-cr3
add_wrr_htb_dscp LER_Ingress leri-cr3 "$CR3_BW" "$cr3_hi" "$cr3_me" "$cr3_lo" "$CR3_DELAY" "$DELAY_ME" "$DELAY_LO"
echo "  LER_Ingress:leri-cr3  total=${CR3_BW} hi=${cr3_hi} me=${cr3_me} lo=${cr3_lo} delay=${CR3_DELAY} (+me=${DELAY_ME} +lo=${DELAY_LO})"

# ----------------------------------------------------------------
# 3. WRR + 帯域 + 遅延 - CoreRouter egress to LER_Egress
# ----------------------------------------------------------------
echo ""
echo "=== WRR 4:2:1 + 帯域制限 + 遅延 (CoreRouter -> LER_Egress, パターンA) ==="
clear_qdisc CoreRouter1 cr1-lere
add_wrr_htb_dscp CoreRouter1 cr1-lere "$CR1_BW" "$cr1_hi" "$cr1_me" "$cr1_lo" "$CR1_DELAY"
echo "  CoreRouter1:cr1-lere  total=${CR1_BW} delay=${CR1_DELAY}"

clear_qdisc CoreRouter2 cr2-lere
add_wrr_htb_dscp CoreRouter2 cr2-lere "$CR2_BW" "$cr2_hi" "$cr2_me" "$cr2_lo" "$CR2_DELAY"
echo "  CoreRouter2:cr2-lere  total=${CR2_BW} delay=${CR2_DELAY}"

clear_qdisc CoreRouter3 cr3-lere
add_wrr_htb_dscp CoreRouter3 cr3-lere "$CR3_BW" "$cr3_hi" "$cr3_me" "$cr3_lo" "$CR3_DELAY"
echo "  CoreRouter3:cr3-lere  total=${CR3_BW} delay=${CR3_DELAY}"

# ----------------------------------------------------------------
# 4. DropTail 100pkt - LER_Egress egress to Rx hosts
# ----------------------------------------------------------------
echo ""
echo "=== DropTail ${DROPTAIL_PKTS}pkt (LER_Egress -> Rx) ==="
<<<<<<< HEAD
for dev in rx1-out rx2-out rx3-out; do
=======
for dev in lere-rx1 lere-rx2 lere-rx3; do
>>>>>>> a871d29236fc25033b139708afa500660335c698
    clear_qdisc LER_Egress "$dev"
    add_droptail LER_Egress "$dev"
    echo "  LER_Egress:$dev"
done

# ----------------------------------------------------------------
# 5. Ingress policing (LER_Ingress leri-tx1/2/3) - WRR 4:2:1 強制
#    全クラス共通: 全3リンク合計帯域の WRR シェアを上限とする
#    総帯域 = CR1_BW + CR2_BW + CR3_BW
# ----------------------------------------------------------------
echo ""
<<<<<<< HEAD
echo "=== Ingress policing (tx1-in/tx2-in/tx3-in, WRR 4:2:1) ==="
=======
echo "=== Ingress policing (leri-tx1/2/3, WRR 4:2:1) ==="
>>>>>>> a871d29236fc25033b139708afa500660335c698

total_bw_kbps=$(( $(rate_to_kbps "$CR1_BW") + $(rate_to_kbps "$CR2_BW") + $(rate_to_kbps "$CR3_BW") ))
total_bw_tc="${total_bw_kbps}kbit"
read -r ingress_hi ingress_me ingress_lo <<< "$(wrr_subrates "$total_bw_tc")"

# burst = rate[kbps] × 1000 / 8 / 100 (10ms バースト, 最小 16KB)
_pb() { local b=$(( $1 * 1000 / 8 / 100 )); echo $(( b < 16384 ? 16384 : b )); }
hi_kbps=$(rate_to_kbps "$ingress_hi")
me_kbps=$(rate_to_kbps "$ingress_me")
lo_kbps=$(rate_to_kbps "$ingress_lo")
pb_hi=$(_pb "$hi_kbps")
pb_me=$(_pb "$me_kbps")
pb_lo=$(_pb "$lo_kbps")

<<<<<<< HEAD
for dev in tx1-in tx2-in tx3-in; do
    ip netns exec LER_Ingress tc qdisc del dev "$dev" ingress 2>/dev/null || true
done

ip netns exec LER_Ingress tc qdisc add dev tx1-in handle ffff: ingress
ip netns exec LER_Ingress tc filter add dev tx1-in parent ffff: protocol all \
    u32 match u32 0 0 \
    police rate "$ingress_hi" burst "${pb_hi}b" drop flowid :1

ip netns exec LER_Ingress tc qdisc add dev tx2-in handle ffff: ingress
ip netns exec LER_Ingress tc filter add dev tx2-in parent ffff: protocol all \
    u32 match u32 0 0 \
    police rate "$ingress_me" burst "${pb_me}b" drop flowid :1

ip netns exec LER_Ingress tc qdisc add dev tx3-in handle ffff: ingress
ip netns exec LER_Ingress tc filter add dev tx3-in parent ffff: protocol all \
=======
for dev in leri-tx1 leri-tx2 leri-tx3; do
    docker exec LER_Ingress tc qdisc del dev "$dev" ingress 2>/dev/null || true
done

docker exec LER_Ingress tc qdisc add dev leri-tx1 handle ffff: ingress
docker exec LER_Ingress tc filter add dev leri-tx1 parent ffff: protocol all \
    u32 match u32 0 0 \
    police rate "$ingress_hi" burst "${pb_hi}b" drop flowid :1

docker exec LER_Ingress tc qdisc add dev leri-tx2 handle ffff: ingress
docker exec LER_Ingress tc filter add dev leri-tx2 parent ffff: protocol all \
    u32 match u32 0 0 \
    police rate "$ingress_me" burst "${pb_me}b" drop flowid :1

docker exec LER_Ingress tc qdisc add dev leri-tx3 handle ffff: ingress
docker exec LER_Ingress tc filter add dev leri-tx3 parent ffff: protocol all \
>>>>>>> a871d29236fc25033b139708afa500660335c698
    u32 match u32 0 0 \
    police rate "$ingress_lo" burst "${pb_lo}b" drop flowid :1

echo "  総帯域: ${total_bw_tc}"
<<<<<<< HEAD
echo "  tx1-in (AF41 高優先): police rate ${ingress_hi} burst ${pb_hi}b"
echo "  tx2-in (AF42 中優先): police rate ${ingress_me} burst ${pb_me}b"
echo "  tx3-in (AF43 低優先): police rate ${ingress_lo} burst ${pb_lo}b"

echo ""
echo "TC 設定完了"
echo "確認: ip netns exec LER_Ingress tc qdisc show"
=======
echo "  leri-tx1 (AF41 高優先): police rate ${ingress_hi} burst ${pb_hi}b"
echo "  leri-tx2 (AF42 中優先): police rate ${ingress_me} burst ${pb_me}b"
echo "  leri-tx3 (AF43 低優先): police rate ${ingress_lo} burst ${pb_lo}b"

echo ""
echo "TC 設定完了"
echo "確認: docker exec LER_Ingress tc qdisc show"
>>>>>>> a871d29236fc25033b139708afa500660335c698
