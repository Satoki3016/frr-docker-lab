#!/bin/bash
# physical2_frr_measure_sw1.sh
# SW1で実行: TE経路設定 + iperf3/OWDクライアント起動 + 障害注入
#
# 使い方:
#   sudo bash /home/kannolab/scripts/physical2_frr_measure_sw1.sh [duration] [normal|failure|failure_reroute]
#
# 注意: SW2のphysical2_frr_measure_sw2.shを先に起動すること

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export LAB_MODE=physical
source "${SCRIPT_DIR}/lab_config.sh"

DURATION=${1:-60}
SCENARIO=${2:-normal}
RESULTS_DIR="/tmp/frr_results_${SCENARIO}"

if ! [[ "$DURATION" =~ ^[0-9]+$ ]]; then
    echo "[ERROR] durationは数値で指定してください: '$DURATION'"
    exit 1
fi

# 前回の残骸をクリーンアップ（自分自身・親プロセスは除外）
for pid in $(pgrep -f "physical2_frr_measure_sw1" 2>/dev/null); do
    [ "$pid" = "$$" ] || [ "$pid" = "$PPID" ] || kill -9 "$pid" 2>/dev/null || true
done
for c in Tx1 Tx2 Tx3; do
    docker exec "$c" pkill -9 -f iperf3 2>/dev/null || true
    docker exec "$c" pkill -9 -f owd_sender 2>/dev/null || true
done
sleep 1
if ! [[ "$SCENARIO" =~ ^(normal|failure|failure_reroute)$ ]]; then
    echo "[ERROR] シナリオは normal / failure / failure_reroute のいずれか"
    exit 1
fi

mkdir -p "$RESULTS_DIR"

# ── 前回実行のorphanモニターを終了 ────────────────────────────────────────
_PID_FILE="/tmp/htb_monitor_pids"
if [ -f "$_PID_FILE" ]; then
    while read -r _pid; do
        kill "$_pid" 2>/dev/null || true
    done < "$_PID_FILE"
    rm -f "$_PID_FILE"
fi

echo "████████████████████████████████████████"
echo "  SW1 計測 [${SCENARIO}] ${DURATION}s"
echo "████████████████████████████████████████"
echo "  結果保存: $RESULTS_DIR"

# ── OSPF-SR ラベル動的取得 ──────────────────────────────────────────────
echo ""
echo "=== [1] OSPF-SR ラベル取得 ==="
LERE_LABEL=$(docker exec frr-LER_Ingress ip route show 192.168.0.5/32 2>/dev/null \
    | grep -oP '(?<=encap mpls )[0-9]+' | head -1 || true)
if [ -z "$LERE_LABEL" ]; then
    LERE_LABEL=$(docker exec frr-LER_Ingress vtysh \
        -c "show mpls table" 2>/dev/null \
        | awk '$1~/^1[0-9]{4}$/ && $2=="SR" && $3=="(OSPF)" {print $1; exit}' || true)
fi
LERE_LABEL=${LERE_LABEL:-16005}
echo "  LER_Egress SID: ${LERE_LABEL}"

# ── TC catch-allフィルタ削除 ─────────────────────────────────────────────
# pref 10のu32キャッチオールは未分類TCP(iperf3制御)をAF43 netemに流してしまう
# TCPコネクション確立を妨げるため測定前に削除する
echo ""
echo "=== [2a] TC catch-allフィルタ削除 ==="
for dev in leri-cr1 leri-cr2 leri-cr3; do
    docker exec LER_Ingress tc filter del dev "$dev" pref 10 2>/dev/null && \
        echo "  [fix] LER_Ingress:${dev} catch-all削除" || true
done
for cname_dev in "CR1:cr1-lere" "CR2:cr2-lere" "CR3:cr3-lere"; do
    cname="${cname_dev%%:*}"; dev="${cname_dev##*:}"
    docker exec "$cname" tc filter del dev "$dev" pref 10 2>/dev/null && \
        echo "  [fix] ${cname}:${dev} catch-all削除" || true
done

# ── leri-tx3 ingress police 更新 ──────────────────────────────────────────
# frr_dscp_te.sh は leri-tx3 をAF43専用(~42Mbps)としてポリシングしているが
# 全3ストリームをTx3経由に変更したため、CR1+CR2+CR3合計帯域(300M)に拡張する。
# HTB WRR(leri-cr1)が引き続きAF41:AF42:AF43=4:2:1 の割り当てを行う。
# TCP(iperf3制御コネクション)はpoliceをバイパスさせる。
# UDPのみポリシング対象にすることで、500Mbps UDPフラッドによるバケット枯渇が
# TCPのSYNパケットをドロップしてNETUNREACHを引き起こす問題を回避する。
echo ""
echo "=== [2b] leri-tx3 ingress police 更新 (42M→300M, TCP exempt) ==="
source "${SCRIPT_DIR}/lab_config.sh" 2>/dev/null || true
_rate_to_kbps() {
    local r; r=$(echo "$1" | tr '[:upper:]' '[:lower:]')
    case "$r" in
        *mbit|*mbps|*m) echo $(( ${r//[^0-9]/} * 1000 )) ;;
        *kbit|*kbps|*k) echo "${r//[^0-9]/}" ;;
        *gbit|*gbps|*g) echo $(( ${r//[^0-9]/} * 1000000 )) ;;
        *) echo "${r//[^0-9]/}" ;;
    esac
}
_total_kbps=$(( $(_rate_to_kbps "${CR1_BW:-10G}") + $(_rate_to_kbps "${CR2_BW:-10G}") + $(_rate_to_kbps "${CR3_BW:-10G}") ))
_burst_b=$(( _total_kbps * 1000 / 8 / 20 ))
[ "$_burst_b" -lt 131072 ] && _burst_b=131072
docker exec LER_Ingress tc qdisc del dev leri-tx3 ingress 2>/dev/null || true
docker exec LER_Ingress tc qdisc add dev leri-tx3 handle ffff: ingress
# prio 10: TCPはpolice不要(制御コネクション用) → 無条件通過
docker exec LER_Ingress tc filter add dev leri-tx3 parent ffff: protocol ip prio 10 \
    u32 match ip protocol 6 0xff \
    flowid :1
# prio 20: UDPをCR合計帯域(300M)でポリシング
docker exec LER_Ingress tc filter add dev leri-tx3 parent ffff: protocol ip prio 20 \
    u32 match ip protocol 17 0xff \
    police rate "${_total_kbps}kbit" burst "${_burst_b}b" mtu 9000 drop flowid :1
# prio 30: その他(ICMP等)もポリシング対象
docker exec LER_Ingress tc filter add dev leri-tx3 parent ffff: protocol all prio 30 \
    u32 match u32 0 0 \
    police rate "${_total_kbps}kbit" burst "${_burst_b}b" mtu 9000 drop flowid :1
echo "  [ok] leri-tx3: TCP→pass / UDP+other police ${_total_kbps}kbit (burst ${_burst_b}b)"

# ── iptables PREROUTING更新 ──────────────────────────────────────────────
# 実環境のPREROUTINGはDSCPベース: udp dpt→DSCP set → DSCP match→mark set
# port 5101(AF41 UDP)のDSCPルールが未登録のため追加する
# TCP制御コネクションはiperf3 -S オプションでTOSを設定してDSCPを付与する
echo ""
echo "=== [2c] iptables PREROUTING更新 (UDP port 5101→DSCP AF41 追加) ==="
docker exec LER_Ingress iptables -t mangle -I PREROUTING 1 -p udp --dport 5101 \
    -j DSCP --set-dscp-class AF41 2>/dev/null || true
echo "  [ok] UDP dport 5101→DSCP AF41 (TCP制御はiperf3 -S 0x88/0x90 で対処)"

# ── シナリオ別TE経路設定 ─────────────────────────────────────────────────
echo ""
echo "=== [2] TE経路設定 (table 41/42/43) ==="
pkill -f "frr_te_monitor.sh" 2>/dev/null || true
sleep 0.3

TE_MONITOR_PID=""
case "$SCENARIO" in
normal)
    echo "  全クラス→CR1主経路 (CR2/CR3フォールバック)"
    for tbl in 41 42 43; do
        docker exec LER_Ingress ip route flush table "$tbl" 2>/dev/null || true
        docker exec LER_Ingress ip route add table "$tbl" 10.20.0.0/16 \
            encap mpls "${LERE_LABEL}" via 10.0.1.2 dev leri-cr1 metric 1 \
            || { echo "  [warn] table $tbl CR1 route add failed"; }
        docker exec LER_Ingress ip route add table "$tbl" 10.20.0.0/16 \
            encap mpls "${LERE_LABEL}" via 10.0.3.2 dev leri-cr2 metric 2 \
            2>/dev/null || echo "  [warn] table $tbl CR2 route add failed (continuing)"
    done
    docker exec LER_Ingress ip route add table 43 10.20.0.0/16 \
        encap mpls "${LERE_LABEL}" via 10.0.5.2 dev leri-cr3 metric 3 \
        2>/dev/null || echo "  [warn] table 43 CR3 route add failed (continuing)"
    echo "  [ok] 全クラス→CR1(metric1)/CR2(metric2)/CR3(metric3)"
    ;;
failure)
    # tc netem loss 100% で leri-cr1 の全パケットを廃棄 (operstate は UP のまま)
    # unreachable 注入不要: netem がデータ + OSPF hello を自然にドロップ
    echo "  全クラス→CR1専用 (netem loss 100% で自然ブラックホール / unreachable 注入なし)"
    for tbl in 41 42 43; do
        docker exec LER_Ingress ip route flush table "$tbl" 2>/dev/null || true
        docker exec LER_Ingress ip route add table "$tbl" 10.20.0.0/16 \
            encap mpls "${LERE_LABEL}" via 10.0.1.2 dev leri-cr1 metric 1
    done
    echo "  [ok] CR1専用 (netem 100%損失 → t=20-40 全クラス通信断)"
    ;;
failure_reroute)
    # OSPF タイマー短縮 + frr_te_monitor の OSPF ポーリングで netem 障害を ~5s 以内に検知
    echo "  初期TE経路: CR1専用 (OSPF タイマー短縮 + frr_te_monitor OSPF ポーリング)"
    echo "  OSPF タイマー短縮 (hello=1s / dead=3s) を設定中..."
    docker exec frr-LER_Ingress vtysh -c "conf t" \
        -c "interface leri-cr1" \
        -c " ip ospf hello-interval 1" \
        -c " ip ospf dead-interval 3" 2>/dev/null \
        && echo "  [ok] LER_Ingress leri-cr1: hello=1s dead=3s" \
        || echo "  [warn] LER_Ingress OSPF タイマー設定失敗 (継続)"
    docker exec frr-CR1 vtysh -c "conf t" \
        -c "interface cr1-leri" \
        -c " ip ospf hello-interval 1" \
        -c " ip ospf dead-interval 3" 2>/dev/null \
        && echo "  [ok] CR1 cr1-leri: hello=1s dead=3s" \
        || echo "  [warn] CR1 OSPF タイマー設定失敗 (継続)"
    for tbl in 41 42 43; do
        docker exec LER_Ingress ip route flush table "$tbl" 2>/dev/null || true
        docker exec LER_Ingress ip route add table "$tbl" 10.20.0.0/16 \
            encap mpls "${LERE_LABEL}" via 10.0.1.2 dev leri-cr1 metric 1
    done
    echo "  [ok] 初期ルート設定完了 (CR1専用 / unreachable なし)"
    echo "  frr_te_monitor起動 (OSPF ポーリング + netlink 二重監視)"
    bash "${SCRIPT_DIR}/frr_te_monitor.sh" /tmp/frr_te_monitor.log > /dev/null 2>&1 &
    TE_MONITOR_PID=$!
    echo "  [ok] frr_te_monitor PID=$TE_MONITOR_PID"
    sleep 3
    ;;
esac

# ── 障害注入スケジュール ──────────────────────────────────────────────────
FAILURE_PID=""
if [[ "$SCENARIO" = "failure" || "$SCENARIO" = "failure_reroute" ]]; then
    echo ""
    echo "=== [3] 障害注入スケジュール ==="
    echo "  t=20s: leri-cr1 DOWN / t=40s: leri-cr1 UP"
    (
        set +e
        sleep 20
        echo "[t=20s] leri-cr1 netem loss 100% → リンク劣化シミュレート" >> /tmp/failure_inject.log
        # operstate は UP のまま全パケット (データ + OSPF hello) を廃棄
        docker exec LER_Ingress tc qdisc add dev leri-cr1 root netem loss 100%
        sleep 20
        echo "[t=40s] leri-cr1 netem 解除 → 自然復旧" >> /tmp/failure_inject.log
        # netem 解除後はルートが変わっていないため再設定不要
        docker exec LER_Ingress tc qdisc del dev leri-cr1 root 2>/dev/null || true
    ) > /dev/null 2>&1 &
    FAILURE_PID=$!
fi

# ── SW2サーバー準備待ち ──────────────────────────────────────────────────
echo ""
echo "=== [4] SW2サーバー起動確認待ち (10s) ==="
sleep 10

# ── iperf3/OWD クライアント起動 ──────────────────────────────────────────
echo ""
echo "=== [5] 計測開始 (${DURATION}s) ==="
echo "  送信レート: Tx1=${TX1_RATE} / Tx2=${TX2_RATE} / Tx3=${TX3_RATE}"
echo "  MPLS SID: ${LERE_LABEL}"

for tx in Tx1 Tx2 Tx3; do
    docker cp "${SCRIPT_DIR}/owd_sender.py" "${tx}:/tmp/owd_sender.py"
done

docker exec -d Tx1 python3 /tmp/owd_sender.py \
    --dst 10.20.1.1 --port 5001 --dscp 34 --interval 0.02 --duration "$DURATION" --label "AF41"
docker exec -d Tx2 python3 /tmp/owd_sender.py \
    --dst 10.20.2.1 --port 5002 --dscp 36 --interval 0.02 --duration "$DURATION" --label "AF42"
docker exec -d Tx3 python3 /tmp/owd_sender.py \
    --dst 10.20.3.1 --port 5003 --dscp 38 --interval 0.02 --duration "$DURATION" --label "AF43"
echo "  [ok] OWD 送信プロセス起動"

# パス統計モニター起動 (leri-cr1 TX / cr1-leri RX の逐次記録)
PATH_CSV="${RESULTS_DIR}/path_stats.csv"
rm -f "$PATH_CSV"
echo "time,leri_cr1_tx_bps,cr1_leri_rx_bps,leri_cr1_drops,cr1_leri_drops" > "$PATH_CSV"
LERI_PID=$(docker inspect --format '{{.State.Pid}}' LER_Ingress)
CR1_PID=$(docker inspect  --format '{{.State.Pid}}' CR1)
(
    set +e
    t_start_ms=$(date +%s%3N)
    t_prev_ms=$t_start_ms
    get_stats() {
        # leri-cr1 TX bytes ($10) and TX drops ($13)
        awk '$1=="leri-cr1:"{printf "%s %s\n",$10,$13}' \
            "/proc/${LERI_PID}/net/dev" 2>/dev/null || echo "0 0"
    }
    get_cr1() {
        # cr1-leri RX bytes ($2) and RX drops ($5)
        awk '$1=="cr1-leri:"{printf "%s %s\n",$2,$5}' \
            "/proc/${CR1_PID}/net/dev" 2>/dev/null || echo "0 0"
    }
    read -r prev_tx prev_td < <(get_stats)
    read -r prev_rx prev_rd < <(get_cr1)
    prev_tx=${prev_tx:-0}; prev_td=${prev_td:-0}
    prev_rx=${prev_rx:-0}; prev_rd=${prev_rd:-0}
    while true; do
        sleep 1
        read -r b_tx b_td < <(get_stats)
        read -r b_rx b_rd < <(get_cr1)
        [[ "$b_tx" =~ ^[0-9]+$ && "$b_rx" =~ ^[0-9]+$ ]] || continue
        now_ms=$(date +%s%3N)
        t=$(( (now_ms - t_start_ms) / 1000 ))
        dt=$(( now_ms - t_prev_ms )); [ "$dt" -le 0 ] && dt=1000
        tx_bps=$(( (b_tx - prev_tx) * 1000 / dt ))
        rx_bps=$(( (b_rx - prev_rx) * 1000 / dt ))
        td=$((  b_td - prev_td )); rx_d=$(( b_rd - prev_rd ))
        [ "$tx_bps" -lt 0 ] && tx_bps=0; [ "$rx_bps" -lt 0 ] && rx_bps=0
        echo "$t,$tx_bps,$rx_bps,$td,$rx_d" >> "$PATH_CSV"
        prev_tx=$b_tx; prev_td=$b_td; prev_rx=$b_rx; prev_rd=$b_rd
        t_prev_ms=$now_ms
    done
) > /dev/null 2>&1 &
PATH_MON_PID=$!

# HTB クラス別スループットモニター (leri-cr1 WRR per-class bytes)
HTB_CSV="${RESULTS_DIR}/htb_class_stats.csv"
rm -f "$HTB_CSV"
echo "time,af41_bps,af42_bps,af43_bps" > "$HTB_CSV"
(
    set +e
    _MON_DEV=leri-cr1
    _MON_CSV="$HTB_CSV"
    t_start_ms=$(date +%s%3N)
    t_prev_ms=$t_start_ms
    get_htb_bytes() {
        docker exec LER_Ingress tc -s class show dev "$_MON_DEV" 2>/dev/null | \
        awk '
            /^class htb 1:/ { if ($3=="1:1") cls=1; else if ($3=="1:2") cls=2; else if ($3=="1:3") cls=3; else cls=0 }
            / Sent / && cls>0 { for(i=2;i<=NF;i++) { if($i=="bytes"){ b[cls]=$(i-1)+0; cls=0; break } } }
            END { printf "%.0f %.0f %.0f\n", b[1]+0, b[2]+0, b[3]+0 }
        '
    }
    read -r p1 p2 p3 < <(get_htb_bytes)
    p1=${p1:-0}; p2=${p2:-0}; p3=${p3:-0}
    t_target_ms=$(( t_start_ms + 1000 ))
    while true; do
        now_ms=$(date +%s%3N)
        rem=$(( t_target_ms - now_ms ))
        [ "$rem" -gt 0 ] && sleep "$(printf '%d.%03d' $((rem/1000)) $((rem%1000)))"
        read -r b1 b2 b3 < <(get_htb_bytes)
        [[ "$b1" =~ ^[0-9]+$ ]] || { t_target_ms=$(( t_target_ms + 1000 )); continue; }
        now_ms=$(date +%s%3N)
        t=$(( (now_ms - t_start_ms) / 1000 ))
        dt=$(( now_ms - t_prev_ms )); [ "$dt" -le 0 ] && dt=1000
        bps1=$(( (b1 - p1) * 1000 / dt ))
        bps2=$(( (b2 - p2) * 1000 / dt ))
        bps3=$(( (b3 - p3) * 1000 / dt ))
        [ "$bps1" -lt 0 ] && bps1=0
        [ "$bps2" -lt 0 ] && bps2=0
        [ "$bps3" -lt 0 ] && bps3=0
        echo "$t,$bps1,$bps2,$bps3" >> "$_MON_CSV"
        p1=$b1; p2=$b2; p3=$b3
        t_prev_ms=$now_ms
        t_target_ms=$(( t_target_ms + 1000 ))
    done
) > /dev/null 2>&1 &
HTB_MON_PID=$!

# HTB クラス別スループットモニター (leri-cr2 — failure_reroute 時に te_monitor がここに切り替え)
HTB_CR2_CSV="${RESULTS_DIR}/htb_class_stats_cr2.csv"
rm -f "$HTB_CR2_CSV"
echo "time,af41_bps,af42_bps,af43_bps" > "$HTB_CR2_CSV"
(
    set +e
    _MON_DEV=leri-cr2
    _MON_CSV="$HTB_CR2_CSV"
    t_start_ms=$(date +%s%3N)
    t_prev_ms=$t_start_ms
    get_htb_bytes() {
        docker exec LER_Ingress tc -s class show dev "$_MON_DEV" 2>/dev/null | \
        awk '
            /^class htb 1:/ { if ($3=="1:1") cls=1; else if ($3=="1:2") cls=2; else if ($3=="1:3") cls=3; else cls=0 }
            / Sent / && cls>0 { for(i=2;i<=NF;i++) { if($i=="bytes"){ b[cls]=$(i-1)+0; cls=0; break } } }
            END { printf "%.0f %.0f %.0f\n", b[1]+0, b[2]+0, b[3]+0 }
        '
    }
    read -r p1 p2 p3 < <(get_htb_bytes)
    p1=${p1:-0}; p2=${p2:-0}; p3=${p3:-0}
    t_target_ms=$(( t_start_ms + 1000 ))
    while true; do
        now_ms=$(date +%s%3N)
        rem=$(( t_target_ms - now_ms ))
        [ "$rem" -gt 0 ] && sleep "$(printf '%d.%03d' $((rem/1000)) $((rem%1000)))"
        read -r b1 b2 b3 < <(get_htb_bytes)
        [[ "$b1" =~ ^[0-9]+$ ]] || { t_target_ms=$(( t_target_ms + 1000 )); continue; }
        now_ms=$(date +%s%3N)
        t=$(( (now_ms - t_start_ms) / 1000 ))
        dt=$(( now_ms - t_prev_ms )); [ "$dt" -le 0 ] && dt=1000
        bps1=$(( (b1 - p1) * 1000 / dt ))
        bps2=$(( (b2 - p2) * 1000 / dt ))
        bps3=$(( (b3 - p3) * 1000 / dt ))
        [ "$bps1" -lt 0 ] && bps1=0
        [ "$bps2" -lt 0 ] && bps2=0
        [ "$bps3" -lt 0 ] && bps3=0
        echo "$t,$bps1,$bps2,$bps3" >> "$_MON_CSV"
        p1=$b1; p2=$b2; p3=$b3
        t_prev_ms=$now_ms
        t_target_ms=$(( t_target_ms + 1000 ))
    done
) > /dev/null 2>&1 &
HTB_MON_CR2_PID=$!

# Tx3ルートキャッシュをクリア (以前のICMP unreachableがキャッシュされている可能性)
docker exec Tx3 ip route flush cache 2>/dev/null || true

# 3クラス同時起動: TCPハンドシェイクをAF43 UDP輻輳が始まる前に全て完了させる。
# sleep 2 を入れると AF43 UDP がクロスSW KNET path (~35-50 Mbps) を飽和させた状態で
# AF42/AF41 が TCP SYN を送ることになり、SYN-ACK が 90% ドロップ → 接続失敗する。
docker exec Tx3 iperf3 -c 10.20.3.1 -p 3000 -u -b "$TX3_RATE" -l 1400 -t "$DURATION" \
    -i 1 > "${RESULTS_DIR}/iperf3_af43.log" 2>&1 &
PID3=$!
docker exec Tx2 iperf3 -c 10.20.2.1 -p 2000 -u -b "$TX2_RATE" -l 1400 -t "$DURATION" \
    -i 1 > "${RESULTS_DIR}/iperf3_af42.log" 2>&1 &
PID2=$!
docker exec Tx1 iperf3 -c 10.20.1.1 -p 5101 -u -b "$TX1_RATE" -l 1400 -t "$DURATION" \
    -i 1 > "${RESULTS_DIR}/iperf3_af41.log" 2>&1 &
PID1=$!

echo "  計測中... ${DURATION}秒待機"
# モニターPIDをファイルに保存 (次回起動時のorphan終了用)
printf '%s\n' "$PATH_MON_PID" "$HTB_MON_PID" "$HTB_MON_CR2_PID" > "$_PID_FILE"
wait $PID1 $PID2 $PID3 || true
kill "$PATH_MON_PID"     2>/dev/null || true
kill "$HTB_MON_PID"     2>/dev/null || true
kill "$HTB_MON_CR2_PID" 2>/dev/null || true
wait "$PATH_MON_PID" "$HTB_MON_PID" "$HTB_MON_CR2_PID" 2>/dev/null || true
rm -f "$_PID_FILE"
echo "  [ok] iperf3 計測完了"

# ── クリーンアップ ───────────────────────────────────────────────────────
[ -n "$FAILURE_PID" ] && { wait "$FAILURE_PID" 2>/dev/null || true; }
# netem が残っている場合は確実に削除
docker exec LER_Ingress tc qdisc del dev leri-cr1 root 2>/dev/null || true
# failure_reroute: OSPF タイマーをデフォルトに戻す
if [ "$SCENARIO" = "failure_reroute" ]; then
    docker exec frr-LER_Ingress vtysh -c "conf t" \
        -c "interface leri-cr1" \
        -c " no ip ospf hello-interval" \
        -c " no ip ospf dead-interval" 2>/dev/null || true
    docker exec frr-CR1 vtysh -c "conf t" \
        -c "interface cr1-leri" \
        -c " no ip ospf hello-interval" \
        -c " no ip ospf dead-interval" 2>/dev/null || true
fi
if [ -n "$TE_MONITOR_PID" ]; then
    kill "$TE_MONITOR_PID" 2>/dev/null || true
    for _i in 1 2 3 4 5; do
        kill -0 "$TE_MONITOR_PID" 2>/dev/null || break
        sleep 0.5
    done
    kill -9 "$TE_MONITOR_PID"  2>/dev/null || true
    pkill -9 -P "$TE_MONITOR_PID" 2>/dev/null || true
    wait "$TE_MONITOR_PID" 2>/dev/null || true
fi
pkill -9 -f "frr_te_monitor.sh" 2>/dev/null || true
for tx in Tx1 Tx2 Tx3; do
    docker exec "$tx" pkill -f "owd_sender" 2>/dev/null || true
done

echo ""
echo "████████████████████████████████████████"
echo "  SW1 計測完了: $RESULTS_DIR"
echo "████████████████████████████████████████"
echo ""
ls -lh "${RESULTS_DIR}/" 2>/dev/null || true
echo ""
echo "■ 次のステップ: SW2の完了後、PCでSCP + グラフ生成"
if [ "$SCENARIO" = "failure_reroute" ]; then
    echo "  cat /tmp/frr_te_monitor.log   # 迂回ログ確認"
fi
