#!/bin/bash
# FRR OSPF-SR + DiffServ-TE ラボ 計測スクリプト (System B: Docker コンテナ)
#
# 使い方:
#   sudo bash scripts/frr_measure.sh [duration] [normal|failure|failure_reroute]
#
# シナリオ:
#   normal         : 障害なし。OSPF-SR + DiffServ-TE + WRR が正常動作
#   failure        : t=20s CR1 ダウン / 迂回なし
#                    単一パスルーティング (AF41→CR1専用, AF43→CR1専用) のため
#                    CR1 障害時に AF41/AF43 が通信断 (t=20-40s の 20秒間)
#                    t=40s CR1 復旧
#   failure_reroute: t=20s CR1 ダウン / OSPF-SR 動的迂回あり
#                    frr_te_monitor が operstate + OSPF 収束を監視し
#                    AF41 を CR2 へ、AF43 を CR2/CR3 ECMP へ動的に切り替え
#                    使用技術: OSPF-SR (動的ラベル) + MPLS encap + DSCP/DiffServ + HTB WRR
#                    t=40s CR1 復旧 → OSPF 再収束後 AF41 を CR1 へ復元
#
# 前提:
#   sudo bash scripts/frr_all_up.sh  が実行済みであること (コンテナ起動 + OSPF 収束)
#   sudo bash scripts/frr_dscp_te.sh が実行済みであること (iptables/TC/HTB/MPLS 設定)
#
# 結果保存先:
#   results/frr/frr_normal/
#   results/frr/frr_failure/
#   results/frr/frr_failure_reroute/

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/lab_config.sh"

DURATION=${1:-60}
SCENARIO=${2:-normal}
EXPERIMENT_NAME=${3:-$(date +%Y%m%d)_experiment}

if ! [[ "$DURATION" =~ ^[0-9]+$ ]]; then
    echo "[ERROR] 第1引数 (duration) は数値で指定してください: '$DURATION'"
    echo "使い方: sudo bash $0 [duration] [normal|failure|failure_reroute] [experiment_name]"
    exit 1
fi
if ! [[ "$SCENARIO" =~ ^(normal|failure|failure_reroute)$ ]]; then
    echo "[ERROR] 第2引数は normal / failure / failure_reroute のいずれかを指定してください"
    echo "使い方: sudo bash $0 [duration] [normal|failure|failure_reroute] [experiment_name]"
    exit 1
fi

FRR_BASE="$LAB_DIR/results/frr/$EXPERIMENT_NAME"
RESULTS_DIR="$FRR_BASE/frr_${SCENARIO}"
mkdir -p "$RESULTS_DIR"

PLOT_SCRIPT="$LAB_DIR/results/frr/plot_frr.py"

echo "████████████████████████████████████████"
echo "  FRR OSPF-SR 計測  [${SCENARIO}]"
echo "████████████████████████████████████████"
echo "  計測時間 : ${DURATION}s"
echo "  結果保存 : $RESULTS_DIR"
echo ""

# ── 前提チェック ──────────────────────────────────────────────────────
if ! docker ps --format '{{.Names}}' | grep -q '^LER_Ingress$'; then
    echo "[ERROR] LER_Ingress コンテナが起動していません"
    echo "  先に: sudo bash scripts/frr_all_up.sh"
    exit 1
fi
if ! docker exec Tx1 which iperf3 > /dev/null 2>&1; then
    echo "[ERROR] Tx1 コンテナに iperf3 がありません"
    exit 1
fi
if ! docker exec LER_Ingress iptables -t mangle -L DSCPMARK 2>/dev/null | grep -q "MARK"; then
    echo "[WARN] iptables DSCP マーキング未設定 — frr_dscp_te.sh を先に実行してください"
    echo "  sudo bash scripts/frr_dscp_te.sh"
fi

# ── frr_te_monitor を一旦停止 ─────────────────────────────────────────
pkill -f "frr_te_monitor.sh" > /dev/null 2>&1 || true
sleep 0.5

# ── OSPF-SR ラベルを動的取得 ──────────────────────────────────────────
echo "=== [1] OSPF-SR ラベル取得 ==="
LERE_LABEL=""
# FRR OSPFのSRGBは16000-23999、LER_Egress SID index=5 → label=16005
# show mpls tableはadj-SID(15xxx)を先に返すため使用不可。IP routeにencap mplsは非挿入。
# 固定値16005を使用する（lab_config.shのSRGB_BASE+index固定構成）
LERE_LABEL=$(docker exec frr-LER_Ingress ip route show 192.168.0.5/32 2>/dev/null \
    | grep -oP '(?<=encap mpls )[0-9]+' | head -1 || true)
LERE_LABEL=${LERE_LABEL:-16005}
echo "  LER_Egress SID: ${LERE_LABEL}"

# ── シナリオ別ルーティング設定 ────────────────────────────────────────
echo ""
echo "=== [2] シナリオ別セットアップ ==="

case "$SCENARIO" in
# ─────────────────────────────────────────────
# normal: 全クラス CR1 主経路 (1リンク3クラス WRR競合)
# ─────────────────────────────────────────────
normal)
    echo "  モード: 正常系 (1リンク3クラス / OSPF-SR + DiffServ-TE + HTB WRR 4:2:1)"
    echo "  全クラスを CR1 主経路に集約 → leri-cr1 上でWRR 4:2:1 が競合"
    for tbl in 41 42 43; do
        docker exec LER_Ingress ip route flush table "$tbl" 2>/dev/null || true
    done
    # AF41/AF42/AF43 いずれも CR1 主経路、CR2→CR3 フォールバック
    for tbl in 41 42; do
        docker exec LER_Ingress ip route add table "$tbl" 10.20.0.0/16 \
            encap mpls "${LERE_LABEL}" via 10.0.1.2 dev leri-cr1 metric 1
        docker exec LER_Ingress ip route add table "$tbl" 10.20.0.0/16 \
            encap mpls "${LERE_LABEL}" via 10.0.3.2 dev leri-cr2 metric 2
    done
    docker exec LER_Ingress ip route add table 43 10.20.0.0/16 \
        encap mpls "${LERE_LABEL}" via 10.0.1.2 dev leri-cr1 metric 1
    docker exec LER_Ingress ip route add table 43 10.20.0.0/16 \
        encap mpls "${LERE_LABEL}" via 10.0.3.2 dev leri-cr2 metric 2
    docker exec LER_Ingress ip route add table 43 10.20.0.0/16 \
        encap mpls "${LERE_LABEL}" via 10.0.5.2 dev leri-cr3 metric 3
    echo "  [ok] table41/42/43: 全クラス→CR1(pri)/CR2(fb)[/CR3(fb)]"
    echo "  [ok] frr_te_monitor 停止済み (障害なしシナリオ)"
    ;;

# ─────────────────────────────────────────────
# failure: 全クラス CR1 専用。t=20s に tc netem loss 100% でリンク劣化を模擬。
#   leri-cr1 の operstate は UP のまま → パケットが自然にブラックホール化。
#   frr_te_monitor なし → 自動迂回なし → t=20-40 の 20秒間 通信断。
# ─────────────────────────────────────────────
failure)
    echo "  モード: 障害あり / 迂回なし (tc netem loss 100% でリンク劣化シミュレート)"
    echo "  全クラス CR1 専用 → netem が全パケットを廃棄 (unreachable 注入なし)"
    for tbl in 41 42 43; do
        docker exec LER_Ingress ip route flush table "$tbl" 2>/dev/null || true
        docker exec LER_Ingress ip route add table "$tbl" 10.20.0.0/16 \
            encap mpls "${LERE_LABEL}" via 10.0.1.2 dev leri-cr1 metric 1
    done
    echo "  [ok] table41/42/43: CR1(metric 1) のみ"
    echo "  [ok] frr_te_monitor 停止済み (自動迂回なし)"
    echo "  [ok] t=20s: netem loss 100% → OSPF hello も落ちる → dead-interval 後に自然収束"
    ;;

# ─────────────────────────────────────────────
# failure_reroute: OSPF 隣接消失検知 + 動的迂回
#   OSPF タイマー短縮 (hello=1s/dead=3s) + frr_te_monitor の OSPF ポーリングで
#   netem 障害を ~5s 以内に検知して CR2 へ切替
# ─────────────────────────────────────────────
failure_reroute)
    echo "  モード: 障害あり / OSPF 隣接消失検知 + 動的迂回あり"
    # OSPF タイマーを短縮: netem 100%損失 → hello 途絶 → dead-interval(3s) で隣接消失
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
    echo "  frr_te_monitor 起動 (OSPF ポーリング + netlink 二重監視)"
    bash "$SCRIPT_DIR/frr_te_monitor.sh" /tmp/frr_te_monitor.log &
    TE_MONITOR_PID=$!
    echo "  [ok] frr_te_monitor PID=$TE_MONITOR_PID"
    sleep 3
    echo "  [ok] 初期テーブル構築完了 (SID=${LERE_LABEL}, WRR ${WRR_HI}:${WRR_ME}:${WRR_LO})"
    echo ""
    echo "  障害発生時の動作:"
    echo "    t=20s: netem loss 100% → OSPF hello 途絶 → dead-interval(3s) → 隣接消失"
    echo "      → frr_te_monitor OSPF ポーリング検知 (~5s) → table41/42/43 全クラスを CR2 へ"
    echo "    t=40s: netem 解除 → OSPF hello 再開 → Full 確立 → CR1 へ復元"
    ;;
esac

echo ""
echo "=== [3] 現在のルーティングテーブル ==="
docker exec LER_Ingress ip route show table 41 2>/dev/null | sed 's/^/  table41: /'
docker exec LER_Ingress ip route show table 42 2>/dev/null | sed 's/^/  table42: /'
docker exec LER_Ingress ip route show table 43 2>/dev/null | sed 's/^/  table43: /'

# ── iperf3 サーバー起動 ────────────────────────────────────────────────
echo ""
echo "=== [4] iperf3 / OWD サーバー起動 ==="
for rx in Rx1 Rx2 Rx3; do
    docker exec "$rx" pkill -f "iperf3"     2>/dev/null || true
    docker exec "$rx" pkill -f "owd_receiver" 2>/dev/null || true
done
sleep 0.5
docker exec -d Rx1 iperf3 -s -p 1000 --forceflush
docker exec -d Rx2 iperf3 -s -p 2000 --forceflush
docker exec -d Rx3 iperf3 -s -p 3000 --forceflush

# OWD 受信プロセスを Rx に配置・起動
for rx in Rx1 Rx2 Rx3; do
    docker cp "$SCRIPT_DIR/owd_receiver.py" "$rx":/tmp/owd_receiver.py
done
docker exec -d Rx1 python3 /tmp/owd_receiver.py --port 5001 \
    --duration "$(( DURATION + 5 ))" --out /tmp/owd_af41.log --label "AF41"
docker exec -d Rx2 python3 /tmp/owd_receiver.py --port 5002 \
    --duration "$(( DURATION + 5 ))" --out /tmp/owd_af42.log --label "AF42"
docker exec -d Rx3 python3 /tmp/owd_receiver.py --port 5003 \
    --duration "$(( DURATION + 5 ))" --out /tmp/owd_af43.log --label "AF43"
sleep 1
echo "  [ok] Rx1:1000(AF41 iperf3) / Rx2:2000(AF42 iperf3) / Rx3:3000(AF43 iperf3)"
echo "  [ok] Rx1:5001(AF41 OWD) / Rx2:5002(AF42 OWD) / Rx3:5003(AF43 OWD)"

# ── スループットモニター ────────────────────────────────────────────────
echo ""
echo "=== [5] スループットモニター起動 ==="
CSV_PATH="$RESULTS_DIR/throughput.csv"
rm -f "$CSV_PATH"
echo "time,rx1_bytes_per_sec,rx2_bytes_per_sec,rx3_bytes_per_sec" > "$CSV_PATH"

# /proc/<pid>/net/dev をホストから直読みして docker exec を完全廃止
# docker exec はプロセス生成コスト (50-200ms) でソフト割り込みを横取りし
# leri-cr1 の txqueuelen をオーバーフローさせる → 全クラス比例スパイクの根本原因
LER_EGRESS_PID=$(docker inspect --format '{{.State.Pid}}' LER_Egress)
NETDEV_FILE="/proc/${LER_EGRESS_PID}/net/dev"
echo "  [ok] LER_Egress PID=${LER_EGRESS_PID} → ${NETDEV_FILE} 直読みモード"

(
    set +e
    t_start_ms=$(date +%s%3N)
    t_prev_ms=$t_start_ms
    # /proc/<pid>/net/dev の TX bytes = 各行の第10フィールド
    # プロセス生成ゼロ・Docker デーモン経由ゼロ
    get_bytes() {
        # %.0f で整数出力を強制: print→科学表記、%d→32bit overflow、%.0f→正確な整数
        awk '$1=="lere-rx1:"{r1=$10} $1=="lere-rx2:"{r2=$10} $1=="lere-rx3:"{r3=$10}
             END{printf "%.0f\n%.0f\n%.0f\n", r1+0, r2+0, r3+0}' "$NETDEV_FILE" 2>/dev/null
    }
    { read -r prev1; read -r prev2; read -r prev3; } < <(get_bytes)
    prev1=${prev1:-0}; prev2=${prev2:-0}; prev3=${prev3:-0}
    while true; do
        sleep 1
        { read -r b1; read -r b2; read -r b3; } < <(get_bytes)
        [[ "$b1" =~ ^[0-9]+$ && "$b2" =~ ^[0-9]+$ && "$b3" =~ ^[0-9]+$ ]] || continue
        now_ms=$(date +%s%3N)
        t=$(( (now_ms - t_start_ms) / 1000 ))
        dt_ms=$(( now_ms - t_prev_ms ))
        [ "$dt_ms" -le 0 ] && dt_ms=1000
        d1=$(( (b1 - prev1) * 1000 / dt_ms ))
        d2=$(( (b2 - prev2) * 1000 / dt_ms ))
        d3=$(( (b3 - prev3) * 1000 / dt_ms ))
        [ "$d1" -lt 0 ] && d1=0
        [ "$d2" -lt 0 ] && d2=0
        [ "$d3" -lt 0 ] && d3=0
        echo "$t,$d1,$d2,$d3" >> "$CSV_PATH"
        prev1=$b1; prev2=$b2; prev3=$b3
        t_prev_ms=$now_ms
    done
) &
THR_MONITOR_PID=$!
echo "  [ok] PID=$THR_MONITOR_PID → $CSV_PATH"

# ── HTB クラスドロップ + IP routing ドロップ モニター ────────────────────
echo ""
echo "=== [5b] ドロップモニター起動 ==="
HTB_CSV="$RESULTS_DIR/tc_drops.csv"
echo "time,node,iface,class,drops_per_sec" > "$HTB_CSV"
IP_DROP_CSV="$RESULTS_DIR/ip_drops.csv"
echo "time,node,out_no_routes_per_sec,tx_drop_cr1_per_sec,tx_drop_cr2_per_sec,tx_drop_cr3_per_sec" > "$IP_DROP_CSV"
LER_INGRESS_PID=$(docker inspect --format '{{.State.Pid}}' LER_Ingress)
NETDEV_LERI="/proc/${LER_INGRESS_PID}/net/dev"
SNMP_LERI="/proc/${LER_INGRESS_PID}/net/snmp"
echo "  [ok] LER_Ingress PID=${LER_INGRESS_PID}"

(
    set +e
    t_start=$(date +%s)
    declare -A prev

    # HTB クラスドロップ (tc -s class show)
    _poll_tc_drops() {
        for dev in leri-cr1 leri-cr2 leri-cr3; do
            nsenter -t "$LER_INGRESS_PID" -n -- tc -s class show dev "$dev" 2>/dev/null \
                | awk -v d="$dev" '
                    /class htb 1:1/ { cls="AF41" }
                    /class htb 1:2/ { cls="AF42" }
                    /class htb 1:3/ { cls="AF43" }
                    cls && /dropped/ {
                        for (i=1; i<=NF; i++)
                            if (index($i, "dropped") > 0) { print d ":" cls ":" $(i+1)+0; break }
                        cls=""
                    }
                '
        done
    }

    # /proc/net/dev から TX drop (col 13) を取得
    _get_tx_drops() {
        awk '
            $1=="leri-cr1:"{cr1=$13}
            $1=="leri-cr2:"{cr2=$13}
            $1=="leri-cr3:"{cr3=$13}
            END{printf "%.0f:%.0f:%.0f\n", cr1+0, cr2+0, cr3+0}
        ' "$NETDEV_LERI" 2>/dev/null
    }

    # /proc/net/snmp から OutNoRoutes を取得
    _get_out_no_routes() {
        awk '
            /^Ip:/ && NR%2==0 {
                for(i=1;i<=NF;i++) if($i=="OutNoRoutes"){print $(i); exit}
            }
        ' "$SNMP_LERI" 2>/dev/null || echo 0
    }

    # TC drops 初期化
    while IFS=: read -r iface cls cnt; do
        prev["tc:${iface}:${cls}"]=${cnt:-0}
    done < <(_poll_tc_drops)
    # IP/TX drops 初期化
    IFS=: read -r p_cr1 p_cr2 p_cr3 < <(_get_tx_drops)
    prev["tx:cr1"]=${p_cr1:-0}; prev["tx:cr2"]=${p_cr2:-0}; prev["tx:cr3"]=${p_cr3:-0}
    prev["ip:no_route"]=$(_get_out_no_routes)

    while true; do
        sleep 1
        t=$(( $(date +%s) - t_start ))

        # HTB クラスドロップ
        while IFS=: read -r iface cls cnt; do
            key="tc:${iface}:${cls}"
            delta=$(( ${cnt:-0} - ${prev[$key]:-0} ))
            [ "$delta" -lt 0 ] && delta=0
            echo "$t,LER_Ingress,$iface,$cls,$delta" >> "$HTB_CSV"
            prev[$key]=${cnt:-0}
        done < <(_poll_tc_drops)

        # TX queue drops + IP routing drops
        IFS=: read -r c_cr1 c_cr2 c_cr3 < <(_get_tx_drops)
        c_nr=$(_get_out_no_routes)
        d_cr1=$(( ${c_cr1:-0} - ${prev["tx:cr1"]:-0} )); [ "$d_cr1" -lt 0 ] && d_cr1=0
        d_cr2=$(( ${c_cr2:-0} - ${prev["tx:cr2"]:-0} )); [ "$d_cr2" -lt 0 ] && d_cr2=0
        d_cr3=$(( ${c_cr3:-0} - ${prev["tx:cr3"]:-0} )); [ "$d_cr3" -lt 0 ] && d_cr3=0
        d_nr=$(( ${c_nr:-0}  - ${prev["ip:no_route"]:-0} )); [ "$d_nr" -lt 0 ] && d_nr=0
        echo "$t,LER_Ingress,$d_nr,$d_cr1,$d_cr2,$d_cr3" >> "$IP_DROP_CSV"
        prev["tx:cr1"]=${c_cr1:-0}; prev["tx:cr2"]=${c_cr2:-0}; prev["tx:cr3"]=${c_cr3:-0}
        prev["ip:no_route"]=${c_nr:-0}
    done
) &
DROP_MONITOR_PID=$!
echo "  [ok] PID=$DROP_MONITOR_PID → $HTB_CSV / $IP_DROP_CSV"

# ── 障害注入プロセス ──────────────────────────────────────────────────
FAILURE_PID=""
if [[ "$SCENARIO" = "failure" || "$SCENARIO" = "failure_reroute" ]]; then
    echo ""
    echo "=== [6] 障害注入設定 ==="
    (
        set +e
        sleep 20
        echo "[t=20s] leri-cr1 netem loss 100% → リンク劣化シミュレート"
        # operstate は UP のまま全パケット (データ + OSPF hello) を廃棄
        docker exec LER_Ingress tc qdisc add dev leri-cr1 root netem loss 100%
        sleep 20
        echo "[t=40s] leri-cr1 netem 解除 → 自然復旧"
        # netem 解除後はルートが変わっていないため再設定不要
        docker exec LER_Ingress tc qdisc del dev leri-cr1 root 2>/dev/null || true
    ) &
    FAILURE_PID=$!
    if [ "$SCENARIO" = "failure" ]; then
        echo "  [ok] t=20s: netem loss 100% (operstate UP維持 / データ+OSPF 全廃棄)"
        echo "  [ok] frr_te_monitor なし → t=20-40 の間 全クラス通信断"
    else
        echo "  [ok] t=20s: netem loss 100% → OSPF dead-interval(3s) → 隣接消失 → CR2 切替"
    fi
    echo "  [ok] t=40s: netem 解除 → OSPF 自然復旧 → CR1 復元"
fi

# ── 計測開始 ─────────────────────────────────────────────────────────
echo ""
echo "=== [7] 計測開始 (${DURATION}s) ==="
echo "  DSCP マーキング: port1000→AF41(mark41) / port2000→AF42(mark42) / port3000→AF43(mark43)"
echo "  MPLS encap: label ${LERE_LABEL} (LER_Egress SID, OSPF-SR 動的取得)"
echo "  WRR 重み: AF41:AF42:AF43 = ${WRR_HI}:${WRR_ME}:${WRR_LO}"
echo "  送信レート: Tx1=${TX1_RATE} / Tx2=${TX2_RATE} / Tx3=${TX3_RATE}"

# OWD 送信プロセスを Tx に配置・起動 (iperf3 と並行)
for tx in Tx1 Tx2 Tx3; do
    docker cp "$SCRIPT_DIR/owd_sender.py" "$tx":/tmp/owd_sender.py
done
docker exec -d Tx1 python3 /tmp/owd_sender.py \
    --dst 10.20.1.1 --port 5001 --dscp 34 --interval 0.02 --duration "$DURATION" --label "AF41"
docker exec -d Tx2 python3 /tmp/owd_sender.py \
    --dst 10.20.2.1 --port 5002 --dscp 36 --interval 0.02 --duration "$DURATION" --label "AF42"
docker exec -d Tx3 python3 /tmp/owd_sender.py \
    --dst 10.20.3.1 --port 5003 --dscp 38 --interval 0.02 --duration "$DURATION" --label "AF43"

# iperf3 UDP — 出力をキャプチャしてパケットロス統計を保存
# -i 1: 毎秒サーバ側の受信統計を記録 → E2E損失率の時系列取得に使用
# --get-server-output: サーバ側の受信統計もクライアント出力に含める
docker exec Tx1 iperf3 -c 10.20.1.1 -p 1000 -u -b "$TX1_RATE" -l 8950 -P 4 -t "$DURATION" \
    -i 1 --get-server-output > "$RESULTS_DIR/iperf3_af41.log" 2>&1 &
PIDS="$!"
docker exec Tx2 iperf3 -c 10.20.2.1 -p 2000 -u -b "$TX2_RATE" -l 8950 -P 4 -t "$DURATION" \
    -i 1 --get-server-output > "$RESULTS_DIR/iperf3_af42.log" 2>&1 &
PIDS="$PIDS $!"
docker exec Tx3 iperf3 -c 10.20.3.1 -p 3000 -u -b "$TX3_RATE" -l 8950 -P 4 -t "$DURATION" \
    -i 1 --get-server-output > "$RESULTS_DIR/iperf3_af43.log" 2>&1 &
PIDS="$PIDS $!"

echo "  計測中... ${DURATION}秒待機"
# shellcheck disable=SC2086
wait $PIDS || true
echo "  計測完了"

# OWD ログ回収 (受信プロセスが終了するまで最大7秒待機)
sleep 3
docker cp Rx1:/tmp/owd_af41.log "$RESULTS_DIR/owd_af41.log" 2>/dev/null || true
docker cp Rx2:/tmp/owd_af42.log "$RESULTS_DIR/owd_af42.log" 2>/dev/null || true
docker cp Rx3:/tmp/owd_af43.log "$RESULTS_DIR/owd_af43.log" 2>/dev/null || true
echo "  [ok] OWD ログ回収完了"

# ── 後処理 ────────────────────────────────────────────────────────────
[ -n "$FAILURE_PID" ] && { wait "$FAILURE_PID" 2>/dev/null || true; }
# netem が残っている場合は確実に削除して復旧
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

kill "$THR_MONITOR_PID"       2>/dev/null || true
kill "${DROP_MONITOR_PID:-}" 2>/dev/null || true

# failure_reroute の場合はモニターも停止
if [ -n "${TE_MONITOR_PID:-}" ]; then
    kill "$TE_MONITOR_PID" 2>/dev/null || true
    for _i in 1 2 3 4 5; do
        kill -0 "$TE_MONITOR_PID" 2>/dev/null || break
        sleep 0.5
    done
    kill -9 "$TE_MONITOR_PID" 2>/dev/null || true
    pkill -9 -P "$TE_MONITOR_PID" 2>/dev/null || true
    wait "$TE_MONITOR_PID" 2>/dev/null || true
fi
pkill -9 -f "frr_te_monitor.sh" > /dev/null 2>&1 || true

for rx in Rx1 Rx2 Rx3; do
    docker exec "$rx" pkill -f "iperf3"       2>/dev/null || true
    docker exec "$rx" pkill -f "owd_receiver" 2>/dev/null || true
done
for tx in Tx1 Tx2 Tx3; do
    docker exec "$tx" pkill -f "owd_sender"   2>/dev/null || true
done

echo ""
echo "=== 収集ファイル ==="
ls -lh "$RESULTS_DIR/"*.csv "$RESULTS_DIR/"*.log "$RESULTS_DIR/"*.json 2>/dev/null || true

echo ""
echo "=== グラフ生成 ==="
if [ -n "$SUDO_USER" ]; then
    chown -R "$SUDO_USER:$SUDO_USER" "$FRR_BASE" 2>/dev/null || true
    PLOT_CMD="sudo -u $SUDO_USER python3"
else
    PLOT_CMD="python3"
fi

# BW → Mbps 変換 (plot_frr.py 引数用)
_bw_to_mbps() {
    local r; r=$(echo "$1" | tr '[:upper:]' '[:lower:]')
    case "$r" in
        *g) echo $(( ${r//[^0-9]/} * 1000 )) ;;
        *m) echo "${r//[^0-9]/}" ;;
        *) echo 100 ;;
    esac
}
CR_MBPS=$(_bw_to_mbps "${CR1_BW:-3G}")

if $PLOT_CMD "$PLOT_SCRIPT" --base "$FRR_BASE" --cr-mbps "$CR_MBPS"; then
    echo "グラフ保存先: $FRR_BASE/figures/"
else
    echo "[WARN] グラフ生成失敗"
fi

echo ""
echo "████████████████████████████████████████"
echo "  計測完了: $RESULTS_DIR"
echo "████████████████████████████████████████"
echo ""
echo "■ 結果確認:"
echo "  head $RESULTS_DIR/throughput.csv"
echo "  ls   $RESULTS_DIR/"
if [ "$SCENARIO" = "failure_reroute" ]; then
    echo "  cat /tmp/frr_te_monitor.log   # 迂回ログ"
fi
