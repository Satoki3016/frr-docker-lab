#!/bin/bash
# DSCP → SR-MPLS 明示経路 + TC/HTB QoS 設定
#
# 動作概要:
#   1. LER_Ingress の iptables でDSCPに応じたfwmarkを付与
#   2. fwmark → ポリシールーティングテーブル(41/42/43)
#   3. 各テーブルに OSPF-SR から動的に取得したラベルで明示経路を設定
#      AF41/AF42/AF43 → 全クラス CR1 主経路 (1リンク3クラス WRR競合)
#      フォールバック: CR2, CR3 (障害時のみ使用)
#   4. TC/HTB WRR 4:2:1 で帯域保証 (CR1 leri-cr1 上で3クラス競合)
#
# OSPFから動的にSIDを取得するため、frr_setup.sh の収束後に実行すること

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lab_config.sh"

dc()  { docker exec "$1" "${@:2}"; }          # docker exec 短縮
frr() { docker exec "frr-$1" vtysh "${@:2}"; } # vtysh 短縮

# ── OSPFからSIDラベルを動的取得 ────────────────────────────────────────
echo "=== [1] OSPF-SR ラベル取得 ==="

# FRRのmpls tableからPrefix SIDを取得
# 形式例: "16005  [1]  Swap,Implicit-Null  192.168.0.5  lere-cr1"
get_label() {
    local container=$1 lo_ip=$2
    frr "$container" -c "show ip ospf segment-routing" 2>/dev/null \
        | grep "$lo_ip" \
        | grep -oP '\b1[0-9]{4}\b' \
        | head -1
}

LERE_LABEL=$(get_label LER_Ingress "192.168.0.5")
CR1_LABEL=$(get_label LER_Ingress  "192.168.0.2")
CR2_LABEL=$(get_label LER_Ingress  "192.168.0.3")
CR3_LABEL=$(get_label LER_Ingress  "192.168.0.4")

# フォールバック: SRGB_base + index
LERE_LABEL=${LERE_LABEL:-16005}
CR1_LABEL=${CR1_LABEL:-16002}
CR2_LABEL=${CR2_LABEL:-16003}
CR3_LABEL=${CR3_LABEL:-16004}

echo "  LER_Egress SID : ${LERE_LABEL}"
echo "  CR1 SID        : ${CR1_LABEL}"
echo "  CR2 SID        : ${CR2_LABEL}"
echo "  CR3 SID        : ${CR3_LABEL}"

# ── iptables DSCP マーキング ──────────────────────────────────────────
echo ""
echo "=== [2] iptables DSCP マーキング (LER_Ingress) ==="
dc LER_Ingress iptables -t mangle -F PREROUTING 2>/dev/null || true
dc LER_Ingress iptables -t mangle -F DSCPMARK   2>/dev/null || true
dc LER_Ingress iptables -t mangle -X DSCPMARK   2>/dev/null || true
dc LER_Ingress iptables -t mangle -N DSCPMARK
dc LER_Ingress iptables -t mangle -A PREROUTING -j DSCPMARK

# 単一パスチェーン: ポート → mark設定 → DSCP設定 → RETURN
# 旧方式: ~8.6 ルール/パケット(WRR加重平均) → 新方式: ~4.7 ルール/パケット

# AF41: iperf3 port 1000 (UDP data + TCP control) + OWD probe port 5001 + legacy port 5101
dc LER_Ingress iptables -t mangle -A DSCPMARK -p tcp -m multiport --dports 5101,1000 \
    -j MARK --set-mark 41
dc LER_Ingress iptables -t mangle -A DSCPMARK -p udp -m multiport --dports 5101,5001,1000 \
    -j MARK --set-mark 41
dc LER_Ingress iptables -t mangle -A DSCPMARK -m mark --mark 41 \
    -j DSCP --set-dscp-class AF41
dc LER_Ingress iptables -t mangle -A DSCPMARK -m mark --mark 41 -j RETURN

# AF42: iperf3 port 2000 (UDP data + TCP control) + OWD probe port 5002
dc LER_Ingress iptables -t mangle -A DSCPMARK -p tcp --dport 2000 \
    -j MARK --set-mark 42
dc LER_Ingress iptables -t mangle -A DSCPMARK -p udp -m multiport --dports 2000,5002 \
    -j MARK --set-mark 42
dc LER_Ingress iptables -t mangle -A DSCPMARK -m mark --mark 42 \
    -j DSCP --set-dscp-class AF42
dc LER_Ingress iptables -t mangle -A DSCPMARK -m mark --mark 42 -j RETURN

# AF43: iperf3 port 3000 (TCP control + UDP data) + OWD probe port 5003
dc LER_Ingress iptables -t mangle -A DSCPMARK -p tcp --dport 3000 \
    -j MARK --set-mark 43
dc LER_Ingress iptables -t mangle -A DSCPMARK -p udp -m multiport --dports 3000,5003 \
    -j MARK --set-mark 43
dc LER_Ingress iptables -t mangle -A DSCPMARK -m mark --mark 43 \
    -j DSCP --set-dscp-class AF43
dc LER_Ingress iptables -t mangle -A DSCPMARK -m mark --mark 43 -j RETURN

# ICMP → AF41 (ping RTT計測用)
dc LER_Ingress iptables -t mangle -A DSCPMARK -p icmp -j MARK --set-mark 41
dc LER_Ingress iptables -t mangle -A DSCPMARK -p icmp -j DSCP --set-dscp-class AF41

echo "  [ok] AF41(port 5101,5001)→mark41 / AF42(port 2000,5002)→mark42 / AF43(port 3000,5003)→mark43"

# ── ポリシールーティングテーブル ─────────────────────────────────────
echo ""
echo "=== [3] ポリシールーティングテーブル (LER_Ingress) ==="

# /etc/iproute2/rt_tables への登録 (コンテナ内、Alpine非対応のためmkdir -p)
dc LER_Ingress bash -c "mkdir -p /etc/iproute2 && { grep -q '^41 ' /etc/iproute2/rt_tables 2>/dev/null || echo '41 rt_af41' >> /etc/iproute2/rt_tables; }" || true
dc LER_Ingress bash -c "grep -q '^42 ' /etc/iproute2/rt_tables 2>/dev/null || echo '42 rt_af42' >> /etc/iproute2/rt_tables" || true
dc LER_Ingress bash -c "grep -q '^43 ' /etc/iproute2/rt_tables 2>/dev/null || echo '43 rt_af43' >> /etc/iproute2/rt_tables" || true

# 既存ルールを削除してから追加
dc LER_Ingress bash -c "
  ip rule list | grep -E 'fwmark (0x29|0x2a|0x2b)' | while read line; do
    prio=\$(echo \"\$line\" | cut -d: -f1)
    ip rule del priority \$prio 2>/dev/null || true
  done
"
dc LER_Ingress ip rule add fwmark 41 table 41 priority 100
dc LER_Ingress ip rule add fwmark 42 table 42 priority 100
dc LER_Ingress ip rule add fwmark 43 table 43 priority 100
echo "  [ok] fwmark 41→table41 / 42→table42 / 43→table43"

# ── SR-MPLS 明示経路設定 ──────────────────────────────────────────────
echo ""
echo "=== [4] SR-MPLS 明示経路 ==="

_add_sr_route() {
    local table=$1 dst=$2 label=$3 via=$4 dev=$5 metric=${6:-1}
    dc LER_Ingress ip route replace table "$table" "$dst" \
        encap mpls "$label" via "$via" dev "$dev" metric "$metric" 2>/dev/null || \
    dc LER_Ingress ip route add    table "$table" "$dst" \
        encap mpls "$label" via "$via" dev "$dev" metric "$metric"
}

dc LER_Ingress ip route flush table 41 2>/dev/null || true
dc LER_Ingress ip route flush table 42 2>/dev/null || true
dc LER_Ingress ip route flush table 43 2>/dev/null || true

# 単一ラベル方式: LER_Egress SID のみ使用
# 経路選択は next-hop (dev leri-crX) で行う。CRのSIDは不要
# (2ラベルスタックでは CR が自SIDをpopした後、内側ラベルをIP扱いして失敗する)

# 全クラス CR1 主経路 (1リンク3クラス: leri-cr1 上でHTB WRR 4:2:1 が競合)
# フォールバック順: CR2(metric 2) → CR3(metric 3)
_add_sr_route 41 10.20.0.0/16 "${LERE_LABEL}" 10.0.1.2 leri-cr1 1
_add_sr_route 41 10.20.0.0/16 "${LERE_LABEL}" 10.0.3.2 leri-cr2 2
echo "  table41 AF41: CR1(primary) / CR2(fallback) → label=${LERE_LABEL}"

_add_sr_route 42 10.20.0.0/16 "${LERE_LABEL}" 10.0.1.2 leri-cr1 1
_add_sr_route 42 10.20.0.0/16 "${LERE_LABEL}" 10.0.3.2 leri-cr2 2
echo "  table42 AF42: CR1(primary) / CR2(fallback) → label=${LERE_LABEL}"

_add_sr_route 43 10.20.0.0/16 "${LERE_LABEL}" 10.0.1.2 leri-cr1 1
_add_sr_route 43 10.20.0.0/16 "${LERE_LABEL}" 10.0.3.2 leri-cr2 2
_add_sr_route 43 10.20.0.0/16 "${LERE_LABEL}" 10.0.5.2 leri-cr3 3
echo "  table43 AF43: CR1(primary) / CR2,CR3(fallback) → label=${LERE_LABEL}"

# ── LER_Egress の MPLS pop + ローカル配送 ────────────────────────────
echo ""
echo "=== [5] LER_Egress MPLS 設定 ==="
# OSPF-SR がFRRのRIBに自動設定するが、明示的に確認のため手動追加も行う
# label 16005 (LER_Egress自身のSID) → pop → Rx宛はOSPFルートで配送
# Rx1/2/3 への直接ルートはOSPFが 10.20.x.x/30 として配布済み
dc LER_Egress bash -c "sysctl -qw net.mpls.conf.lere-cr1.input=1; sysctl -qw net.mpls.conf.lere-cr2.input=1; sysctl -qw net.mpls.conf.lere-cr3.input=1" \
    && echo "  [ok] MPLS入力有効" || echo "  [skip] LER_Egress not on this host (SW2 side)"

# ── TC/HTB WRR 4:2:1 ─────────────────────────────────────────────────
echo ""
echo "=== [6] TC/HTB WRR (LER_Ingress → CoreRouters) ==="

rate_to_kbps() {
    local r; r=$(echo "$1" | tr '[:upper:]' '[:lower:]')
    case "$r" in
        *mbit|*mbps|*m) echo $(( ${r//[^0-9]/} * 1000 )) ;;
        *kbit|*kbps|*k) echo "${r//[^0-9]/}" ;;
        *gbit|*gbps|*g) echo $(( ${r//[^0-9]/} * 1000000 )) ;;
        *) echo 0 ;;
    esac
}
normalize_rate() {
    local r; r=$(echo "$1" | tr '[:upper:]' '[:lower:]')
    case "$r" in *mbit) echo "$r" ;; *mbps) echo "${r%mbps}mbit" ;; *m) echo "${r%m}mbit" ;;
        *kbit) echo "$r" ;; *kbps) echo "${r%kbps}kbit" ;; *k) echo "${r%k}kbit" ;;
        *gbit) echo "$r" ;; *g) echo "${r%g}gbit" ;; *) echo "$r" ;; esac
}
_b() { local b=$(( $1 * 1000 / 8 / 50 )); echo $(( b < 8192 ? 8192 : b )); }

add_htb_wrr() {
    local cname=$1 dev=$2 total=$3
    local tc_rate; tc_rate=$(normalize_rate "$total")
    local total_kbps; total_kbps=$(rate_to_kbps "$total")
    local sum=$(( WRR_HI + WRR_ME + WRR_LO ))
    # 全クラスの保証rateを1/10に縮小: HTBは保証(green)をprioに関係なく先に配るため、
    # 保証を小さくして帯域の約85%を借用(yellow)プールに置く。借用分配は
    # prio=0のAF41が最優先(SP)、残余をAF42/AF43がquantum比2:1(WRR)で分ける。
    local r_hi=$(( total_kbps / 10 ))
    local r_me=$(( total_kbps * WRR_ME / sum / 10 ))
    local r_lo=$(( total_kbps * WRR_LO / sum / 10 ))

    dc "$cname" tc qdisc del dev "$dev" root    2>/dev/null || true
    dc "$cname" tc qdisc add dev "$dev" root handle 1: htb default 13
    dc "$cname" tc class add dev "$dev" parent 1:  classid 1:0 htb rate "$tc_rate" ceil "$tc_rate" \
        burst "$(_b $total_kbps)b" cburst "$(_b $total_kbps)b"
    # AF41: prio 0 (Strict Priority) — 輻輳時に最優先でサービス → 自然に低遅延
    dc "$cname" tc class add dev "$dev" parent 1:0 classid 1:1 htb \
        rate "${r_hi}kbit" ceil "$tc_rate" burst "$(_b $r_hi)b" cburst "$(_b $total_kbps)b" prio 0 quantum $(( WRR_HI * 9000 ))
    # AF42/AF43: prio 1 (WRR) — AF41 充足後に重み比率でサービス → 自然に高遅延
    dc "$cname" tc class add dev "$dev" parent 1:0 classid 1:2 htb \
        rate "${r_me}kbit" ceil "$tc_rate" burst "$(_b $r_me)b" cburst "$(_b $total_kbps)b" prio 1 quantum $(( WRR_ME * 9000 ))
    dc "$cname" tc class add dev "$dev" parent 1:0 classid 1:3 htb \
        rate "${r_lo}kbit" ceil "$tc_rate" burst "$(_b $r_lo)b" cburst "$(_b $total_kbps)b" prio 1 quantum $(( WRR_LO * 9000 ))
    # pfifo リーフ qdisc (netem人工遅延を廃止、自然なキュー遅延で差別化)
    dc "$cname" tc qdisc add dev "$dev" parent 1:1 handle 11: pfifo limit "${PFIFO_LIMIT_HI:-1000}"
    dc "$cname" tc qdisc add dev "$dev" parent 1:2 handle 12: pfifo limit "${PFIFO_LIMIT_ME:-2000}"
    dc "$cname" tc qdisc add dev "$dev" parent 1:3 handle 13: pfifo limit "${PFIFO_LIMIT_LO:-4000}"
    # フィルタ: LER_IngressはDSCP(fwmark)で分類、CoreRouterはMPLS TCで分類
    if [ "$cname" = "LER_Ingress" ]; then
        dc "$cname" tc filter add dev "$dev" parent 1: protocol all prio 1 handle 41 fw flowid 1:1
        dc "$cname" tc filter add dev "$dev" parent 1: protocol all prio 1 handle 42 fw flowid 1:2
        dc "$cname" tc filter add dev "$dev" parent 1: protocol all prio 1 handle 43 fw flowid 1:3
    else
        # MPLSのTraffic Class(TC)ビット (EXPフィールド) でキュー選択
        # DSCP AF41=34(0x22)→EXP4, AF42=36(0x24)→EXP2, AF43=38(0x26)→EXP1
        dc "$cname" tc filter add dev "$dev" parent 1: protocol 0x8847 prio 1 \
            u32 match u32 0x00880000 0x00FC0000 at 4 flowid 1:1
        dc "$cname" tc filter add dev "$dev" parent 1: protocol 0x8847 prio 1 \
            u32 match u32 0x00900000 0x00FC0000 at 4 flowid 1:2
        dc "$cname" tc filter add dev "$dev" parent 1: protocol 0x8847 prio 1 \
            u32 match u32 0x00980000 0x00FC0000 at 4 flowid 1:3
    fi
    echo "  [ok] $cname:$dev  SP+WRR(${WRR_HI}:${WRR_ME}:${WRR_LO})  ${r_hi}/${r_me}/${r_lo}kbit"
}

# LER_Ingress → CoreRouter egress
add_htb_wrr LER_Ingress leri-cr1 "$CR1_BW"
add_htb_wrr LER_Ingress leri-cr2 "$CR2_BW"
add_htb_wrr LER_Ingress leri-cr3 "$CR3_BW"

# CoreRouter → LER_Egress egress
add_htb_wrr CR1 cr1-lere "$CR1_BW"
add_htb_wrr CR2 cr2-lere "$CR2_BW"
add_htb_wrr CR3 cr3-lere "$CR3_BW"

# Ingress policing (leri-tx1/2/3: Tx→LER_Ingress入力)
echo ""
echo "=== [7] Ingress policing (leri-tx1/2/3) ==="
total_kbps=$(( $(rate_to_kbps "$CR1_BW") + $(rate_to_kbps "$CR2_BW") + $(rate_to_kbps "$CR3_BW") ))
sum=$(( WRR_HI + WRR_ME + WRR_LO ))
pb_hi=$(( total_kbps * WRR_HI / sum ))
pb_me=$(( total_kbps * WRR_ME / sum ))
pb_lo=$(( total_kbps * WRR_LO / sum ))
_pb() { local b=$(( $1 * 1000 / 8 / 100 )); echo $(( b < 16384 ? 16384 : b )); }

for dev_rate in "leri-tx1 $pb_hi" "leri-tx2 $pb_me" "leri-tx3 $pb_lo"; do
    dev=${dev_rate% *}; rate=${dev_rate#* }
    dc LER_Ingress tc qdisc del dev "$dev" ingress 2>/dev/null || true
    dc LER_Ingress tc qdisc add dev "$dev" handle ffff: ingress
    dc LER_Ingress tc filter add dev "$dev" parent ffff: protocol all \
        u32 match u32 0 0 \
        police rate "${rate}kbit" burst "$(_pb $rate)b" mtu 9000 drop flowid :1
    echo "  [ok] $dev: police ${rate}kbit"
done

echo ""
echo "=== DiffServ-TE 設定完了 ==="
echo ""
echo "経路確認:"
echo "  docker exec LER_Ingress ip route show table 41"
echo "  docker exec LER_Ingress ip route show table 42"
echo "  docker exec frr-LER_Ingress vtysh -c 'show ip ospf route'"
echo ""
echo "次のステップ: sudo bash scripts/frr_te_monitor.sh &"
