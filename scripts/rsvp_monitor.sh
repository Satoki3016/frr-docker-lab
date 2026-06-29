#!/bin/bash
# RSVP-TE モニター: MPLS-TE FRR (Fast Reroute) シミュレーション
#
# 設計:
#   全クラス ECMP 3経路。CR1 は AF41 の指定プライマリ。
#   障害検知: leri-cr? operstate を監視し、ダウンしたリンクを全クラスの
#             ECMP から除外。復旧時に再追加。
#   AF41 FRR: CR1(プライマリ)がダウンした場合にのみ FRR ログを出力。
#             ECMP 再構築により CR2+CR3 で自動継続。
#
# ECMP ネクストホップ:
#   CR1: AF41=label100, AF42=label200, AF43=label300  via leri-cr1
#   CR2: AF41=label110, AF42=label200, AF43=label310  via leri-cr2
#   CR3: AF41=label120, AF42=label210, AF43=label300  via leri-cr3

LOG_FILE="${1:-/tmp/rsvp_monitor.log}"
INTERVAL=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lab_config.sh"

CR_DEV=(leri-cr1 leri-cr2 leri-cr3)
CR_NH_IP=(10.0.1.2 10.0.3.2 10.0.5.2)
CR_LABEL_AF41=(100 110 120)
CR_LABEL_AF42=(200 200 210)
CR_LABEL_AF43=(300 310 300)

# AF41 の指定プライマリリンクインデックス
AF41_PRIMARY_IDX=0   # leri-cr1

# 各リンクの帯域 (lab_config.sh から)
CR_BW=("$CR1_BW" "$CR2_BW" "$CR3_BW")

# リンク状態: 0=up, 1=down
state=(0 0 0)

rate_to_kbps() {
    local r; r=$(echo "$1" | tr '[:upper:]' '[:lower:]')
    case "$r" in
        *gbit) echo $(( ${r%gbit} * 1000000 )) ;;
        *mbit) echo $(( ${r%mbit} * 1000 )) ;;
        *kbit) echo "${r%kbit}" ;;
        *g)    echo $(( ${r%g}    * 1000000 )) ;;
        *m)    echo $(( ${r%m}    * 1000 )) ;;
        *k)    echo "${r%k}" ;;
        *)     echo 0 ;;
    esac
}

log() {
    local ts; ts=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$ts] $*" | tee -a "$LOG_FILE"
}

get_link_state() {
    ip netns exec LER_Ingress_ns cat /sys/class/net/${CR_DEV[$1]}/operstate 2>/dev/null || echo "unknown"
}

# ----------------------------------------------------------------
# 全クラスの ECMP を up リンクで再構築
# ----------------------------------------------------------------
rebuild_ecmp() {
    local nh41="" nh42="" nh43=""
    local i
    for i in 0 1 2; do
        if [ "${state[$i]}" -eq 0 ]; then
            nh41="$nh41 nexthop encap mpls ${CR_LABEL_AF41[$i]} via ${CR_NH_IP[$i]} dev ${CR_DEV[$i]}"
            nh42="$nh42 nexthop encap mpls ${CR_LABEL_AF42[$i]} via ${CR_NH_IP[$i]} dev ${CR_DEV[$i]}"
            nh43="$nh43 nexthop encap mpls ${CR_LABEL_AF43[$i]} via ${CR_NH_IP[$i]} dev ${CR_DEV[$i]}"
        fi
    done

    if [ -z "$nh41" ]; then
        log "  [WARN] 全リンクダウン: ECMP 更新スキップ"
        return
    fi

    # shellcheck disable=SC2086
    ip netns exec LER_Ingress_ns ip route replace table 41 10.20.1.1/32 $nh41
    # shellcheck disable=SC2086
    ip netns exec LER_Ingress_ns ip route replace table 42 10.20.2.1/32 $nh42
    # shellcheck disable=SC2086
    ip netns exec LER_Ingress_ns ip route replace table 43 10.20.3.1/32 $nh43

    local up=""
    for j in 0 1 2; do [ "${state[$j]}" -eq 0 ] && up="$up CR$((j+1))"; done
    log "  ECMP 再構築: 有効リンク$up"
    rebuild_ingress_police
}

# ----------------------------------------------------------------
# ingress police を有効リンクの合計帯域に合わせて更新 (WRR 比率を維持)
# ----------------------------------------------------------------
rebuild_ingress_police() {
    local total_kbps=0 i
    for i in 0 1 2; do
        [ "${state[$i]}" -eq 0 ] && total_kbps=$(( total_kbps + $(rate_to_kbps "${CR_BW[$i]}") ))
    done
    [ "$total_kbps" -eq 0 ] && return

    local sum=$(( WRR_HI + WRR_ME + WRR_LO ))
    local hi=$(( total_kbps * WRR_HI / sum ))
    local me=$(( total_kbps * WRR_ME / sum ))
    local lo=$(( total_kbps * WRR_LO / sum ))
    # burst = rate[kbps] × 1000 / 8 / 100 (10ms, 最小16KB)
    _pb() { local b=$(( $1 * 1000 / 8 / 100 )); echo $(( b < 16384 ? 16384 : b )); }

    if ip netns exec LER_Ingress_ns ip link show enp23s0f1np1 2>/dev/null | grep -q "enp23s0f1np1"; then
        local _if1="enp23s0f1np1" _if2="enp179s0f1np1" _if3="enp5s0f1"
    else
        local _if1="leri-tx1" _if2="leri-tx2" _if3="leri-tx3"
    fi
    for dev_class in "$_if1 $hi" "$_if2 $me" "$_if3 $lo"; do
        local dev rate_kbps
        dev=${dev_class% *}; rate_kbps=${dev_class#* }
        ip netns exec LER_Ingress_ns tc filter del dev "$dev" parent ffff: 2>/dev/null || true
        ip netns exec LER_Ingress_ns tc filter add dev "$dev" parent ffff: protocol all \
            u32 match u32 0 0 \
            police rate "${rate_kbps}kbit" burst "$(_pb "$rate_kbps")b" drop flowid :1
    done
    log "  ingress police 更新: AF41=${hi}kbit AF42=${me}kbit AF43=${lo}kbit (計${total_kbps}kbit, WRR ${WRR_HI}:${WRR_ME}:${WRR_LO})"
}

# ----------------------------------------------------------------
# 起動
# ----------------------------------------------------------------
log "=== RSVP-TE Monitor (MPLS-TE FRR) Start ==="
log "  AF41 指定プライマリ: ${CR_DEV[$AF41_PRIMARY_IDX]} (CR1)"
log "  監視間隔: ${INTERVAL}s"
log "  WRR: ${WRR_HI}:${WRR_ME}:${WRR_LO}  リンク帯域: CR1=${CR_BW[0]} CR2=${CR_BW[1]} CR3=${CR_BW[2]}"
log ""
# 起動時に現在のリンク状態を確認し ingress police を初期化
# veth の operstate は "up" ではなく "unknown" を返すことがある
# → "down" のみを障害とみなす ("unknown" / "up" はどちらも動作中)
is_down() { [ "$1" = "down" ]; }
is_up()   { [ "$1" != "down" ]; }

for _i in 0 1 2; do
    _ls=$(get_link_state "$_i")
    is_down "$_ls" && state[$_i]=1
done
rebuild_ingress_police
log ""

while true; do
    sleep "$INTERVAL"
    for i in 0 1 2; do
        ls=$(get_link_state "$i")
        cr="CR$((i+1))"

        if [ "${state[$i]}" -eq 0 ] && is_down "$ls"; then
            state[$i]=1
            if [ "$i" -eq "$AF41_PRIMARY_IDX" ]; then
                log "[DOWN] ${cr} (${CR_DEV[$i]}) ダウン ← AF41 PRIMARY LSP 切断"
                log "       MPLS-TE FRR: AF41 を残存リンクに迂回"
            else
                log "[DOWN] ${cr} (${CR_DEV[$i]}) ダウン"
            fi
            rebuild_ecmp

        elif [ "${state[$i]}" -eq 1 ] && is_up "$ls"; then
            state[$i]=0
            if [ "$i" -eq "$AF41_PRIMARY_IDX" ]; then
                log "[UP]   ${cr} (${CR_DEV[$i]}) 復旧 → AF41 PRIMARY LSP 復旧"
            else
                log "[UP]   ${cr} (${CR_DEV[$i]}) 復旧"
            fi
            rebuild_ecmp
        fi
    done
done
