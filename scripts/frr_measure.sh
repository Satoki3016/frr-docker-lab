#!/bin/bash
# FRR OSPF-SR + DiffServ-TE ラボ 計測スクリプト (System B: Docker コンテナ)
#
# 使い方:
#   sudo bash scripts/frr_measure.sh [duration] [normal|failure|failure_reroute|manual]
#   manual         : 自動の障害注入なし・frr_te_monitor あり。障害は人が起こす
#                    (無線 ODU のケーブル抜去など)。3シナリオ比較には含めない。
#   observe        : 通信を流して記録するだけ。経路表・HTB・te_monitor・制御には触らない。
#                    常時動いている te_monitor と動的制御の下で計測する (雨の観測の定時計測)。
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
#   results/frr/incoming/<タグ>/frr_normal/
#   results/frr/incoming/<タグ>/frr_failure/
#   results/frr/incoming/<タグ>/frr_failure_reroute/

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
if ! [[ "$SCENARIO" =~ ^(normal|failure|failure_reroute|manual|observe)$ ]]; then
    echo "[ERROR] 第2引数は normal / failure / failure_reroute / manual / observe のいずれかを指定してください"
    echo "使い方: sudo bash $0 [duration] [normal|failure|failure_reroute|manual|observe] [experiment_name]"
    exit 1
fi

# radwin_experiment.sh run からの明示指定時だけ動的制御を併用する。
# 既存の直接呼び出しと3シナリオ計測は従来どおり。
if [ -n "${RADWIN_CONTROLLER_CSV:-}" ]; then
    # failure は「迂回なし」の比較用。動的制御を重ねると比較の前提が崩れるので除く。
    # failure_reroute では te_monitor が経路表を書き、制御は重みと HTB だけを決める
    # (te_monitor の pidfile で自動判定)。
    if ! [[ "$SCENARIO" =~ ^(normal|failure_reroute|manual)$ ]] || [ "${ROUTE_MODE:-primary}" != "wcmp" ] || [ "${LAB_MODE:-veth}" != "c2" ]; then
        echo "[ERROR] 動的制御の同時計測は LAB_MODE=c2 / ROUTE_MODE=wcmp / normal・failure_reroute・manual 専用です"
        exit 1
    fi
    command -v setsid >/dev/null || { echo "[ERROR] setsid が必要です"; exit 1; }
fi

# PRIO_HI=1 (SP無効化・prio統一ablation) 時は自動でフォルダ名を分け、
# SP有効時の結果を上書きする事故を防ぐ (2026-07-16: 一度上書きした反省による対策)
PRIO_TAG=""
[ "${PRIO_HI:-0}" = "1" ] && PRIO_TAG="_priouniform"

FRR_BASE="${FRR_RESULTS_ROOT:-$LAB_DIR/results/frr/incoming}/$EXPERIMENT_NAME"
RESULTS_DIR="$FRR_BASE/frr_${SCENARIO}${PRIO_TAG}"
mkdir -p "$RESULTS_DIR"

PLOT_SCRIPT="$LAB_DIR/results/frr/plot_frr.py"

echo "████████████████████████████████████████"
echo "  FRR OSPF-SR 計測  [${SCENARIO}]"
echo "████████████████████████████████████████"
echo "  計測時間 : ${DURATION}s"
echo "  PRIOモード: $([ -n "$PRIO_TAG" ] && echo "統一(SP無効化, PRIO_HI=1)" || echo "SP有効(デフォルト)")"
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
# observe は常時動いている te_monitor の下で計測するので止めない。
if [ "$SCENARIO" != "observe" ]; then
    pkill -f "frr_te_monitor.sh" > /dev/null 2>&1 || true
    sleep 0.5
fi

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

# ── ROUTE_MODE=ecmp/wcmp 用: 3経路マルチパスを張る ────────────────────
# 2026-09-17: 従来このスクリプトはシナリオごとに CR1 固定経路をハードコード
#   しており、frr_dscp_te.sh の設定を上書きしていた (マルチパスが効かなかった原因)。
#   ROUTE_MODE が primary 以外なら、ここでもマルチパスを張るようにする。
_mp_weights() {
    if [ "${ROUTE_MODE:-primary}" = "ecmp" ]; then
        echo "1 1 1"
    else
        echo "${WCMP_W1:-1} ${WCMP_W2:-10} ${WCMP_W3:-10}"
    fi
}

# マルチパスはフロー単位(5-tupleハッシュ)で振り分ける。既定の hash_policy=0 は
# 送信元/宛先IPだけを見るため、同一クラスの全フローが同じ経路に行ってしまう。
# docker exec 経由の sysctl はコンテナ権限次第で失敗するので、ホスト側から
# 名前付き netns に入って設定し、必ず値を検証する。
_enable_mp_hash() {
    ip netns exec LER_Ingress sysctl -qw net.ipv4.fib_multipath_hash_policy=1 2>/dev/null \
        || docker exec LER_Ingress sysctl -qw net.ipv4.fib_multipath_hash_policy=1 2>/dev/null || true
    local v
    v=$(ip netns exec LER_Ingress sysctl -n net.ipv4.fib_multipath_hash_policy 2>/dev/null \
        || docker exec LER_Ingress sysctl -n net.ipv4.fib_multipath_hash_policy 2>/dev/null || echo "?")
    if [ "$v" = "1" ]; then
        echo "  [ok] fib_multipath_hash_policy=1 (L3+L4ハッシュ)"
    else
        echo "  [NG] fib_multipath_hash_policy=$v — フローが分散せずクラス単位でしか散らない"
    fi
}

_install_multipath() {
    local w1 w2 w3
    read -r w1 w2 w3 <<< "$(_mp_weights)"
    _enable_mp_hash
    for tbl in 41 42 43; do
        docker exec LER_Ingress ip route flush table "$tbl" 2>/dev/null || true
        docker exec LER_Ingress ip route add table "$tbl" 10.20.0.0/16 \
            nexthop encap mpls "${LERE_LABEL}" via 10.0.1.2 dev leri-cr1 weight "$w1" \
            nexthop encap mpls "${LERE_LABEL}" via 10.0.3.2 dev leri-cr2 weight "$w2" \
            nexthop encap mpls "${LERE_LABEL}" via 10.0.5.2 dev leri-cr3 weight "$w3"
    done
    echo "  [ok] table41/42/43: 3経路マルチパス 重み CR1:CR2:CR3 = ${w1}:${w2}:${w3} (${ROUTE_MODE})"
    echo "       経路選択に優先度は使わない。優先制御は各リンクのHTBのみ。"
}

case "$SCENARIO" in
# ─────────────────────────────────────────────
# normal: 全クラス CR1 主経路 (1リンク3クラス WRR競合)
# ─────────────────────────────────────────────
normal)
    if [ "${ROUTE_MODE:-primary}" != "primary" ]; then
        echo "  モード: 正常系 / 3経路マルチパス (${ROUTE_MODE})"
        _install_multipath
    else
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
    fi
    echo "  [ok] frr_te_monitor 停止済み (障害なしシナリオ)"
    ;;

# ─────────────────────────────────────────────
# failure: 全クラス CR1 専用。t=20s に tc netem loss 100% でリンク劣化を模擬。
#   leri-cr1 の operstate は UP のまま → パケットが自然にブラックホール化。
#   frr_te_monitor なし → 自動迂回なし → t=20-40 の 20秒間 通信断。
# ─────────────────────────────────────────────
failure)
    if [ "${ROUTE_MODE:-primary}" != "primary" ]; then
        echo "  モード: 障害あり / 迂回なし / 3経路マルチパス (${ROUTE_MODE})"
        echo "  CR1 に netem loss 100% を入れるが、経路表は更新しない (迂回なし)"
        _install_multipath
    else
        echo "  モード: 障害あり / 迂回なし (tc netem loss 100% でリンク劣化シミュレート)"
        echo "  全クラス CR1 専用 → netem が全パケットを廃棄 (unreachable 注入なし)"
        for tbl in 41 42 43; do
            docker exec LER_Ingress ip route flush table "$tbl" 2>/dev/null || true
            docker exec LER_Ingress ip route add table "$tbl" 10.20.0.0/16 \
                encap mpls "${LERE_LABEL}" via 10.0.1.2 dev leri-cr1 metric 1
        done
        echo "  [ok] table41/42/43: CR1(metric 1) のみ"
    fi
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
    if [ "${ROUTE_MODE:-primary}" != "primary" ]; then
        _install_multipath
    else
        for tbl in 41 42 43; do
            docker exec LER_Ingress ip route flush table "$tbl" 2>/dev/null || true
            docker exec LER_Ingress ip route add table "$tbl" 10.20.0.0/16 \
                encap mpls "${LERE_LABEL}" via 10.0.1.2 dev leri-cr1 metric 1
        done
    fi
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

# ─────────────────────────────────────────────
# manual: 自動の障害注入なし・frr_te_monitor あり
#   障害は人が起こす (例: 無線 ODU .32 のケーブル抜去)。
#   te_monitor は入口側・出口側の OSPF 隣接 (BFD 300ms×3) を監視し、
#   断を検知した経路を外す。OSPF タイマーは基本設定 (1s/3s) のまま変更しない。
# ─────────────────────────────────────────────
manual)
    echo "  モード: 自動注入なし / 障害は手動 / OSPF 隣接消失検知 + 動的迂回あり"
    if [ "${ROUTE_MODE:-primary}" != "primary" ]; then
        _install_multipath
    else
        for tbl in 41 42 43; do
            docker exec LER_Ingress ip route flush table "$tbl" 2>/dev/null || true
            docker exec LER_Ingress ip route add table "$tbl" 10.20.0.0/16 \
                encap mpls "${LERE_LABEL}" via 10.0.1.2 dev leri-cr1 metric 1
        done
    fi
    echo "  frr_te_monitor 起動 (OSPF ポーリング + netlink 二重監視)"
    bash "$SCRIPT_DIR/frr_te_monitor.sh" /tmp/frr_te_monitor.log &
    TE_MONITOR_PID=$!
    echo "  [ok] frr_te_monitor PID=$TE_MONITOR_PID"
    sleep 3
    echo "  [ok] 初期テーブル構築完了 (SID=${LERE_LABEL}, WRR ${WRR_HI}:${WRR_ME}:${WRR_LO})"
    echo ""
    echo "  障害は手動で起こす。操作した時刻を date +%T で控えること"
    ;;

# ─────────────────────────────────────────────
# observe: 設定に触らず、通信を流して記録するだけ
#   経路表は te_monitor、HTB と重みは常時動いている動的制御が決める。
#   ここで書き換えると、制御は自分が最後に適用した値との差でしか動かないため、
#   上書きされたことに気づかず、誤った整形レートのまま計測してしまう。
# ─────────────────────────────────────────────
observe)
    echo "  モード: 観測 (経路表・HTB・te_monitor・制御には触らない)"
    if pgrep -f "frr_te_monitor.sh" > /dev/null 2>&1; then
        echo "  [ok] frr_te_monitor 稼働中"
    else
        echo "  [WARN] frr_te_monitor が動いていない。無線断で CR1 が外れない"
    fi
    ;;
esac

echo ""
echo "=== [3] 現在のルーティングテーブル ==="
docker exec LER_Ingress ip route show table 41 2>/dev/null | sed 's/^/  table41: /'
docker exec LER_Ingress ip route show table 42 2>/dev/null | sed 's/^/  table42: /'
docker exec LER_Ingress ip route show table 43 2>/dev/null | sed 's/^/  table43: /'

# 経路の初期化完了後に起動する。先に起動すると上のシナリオ設定が動的重みを上書きする。
RADWIN_CONTROLLER_PID=""
_stop_radwin_controller() {
    if [ -n "$RADWIN_CONTROLLER_PID" ]; then
        # setsid で分けた、この計測専用のプロセス群 (SSHを含む) だけを終了する。
        kill -TERM -- "-$RADWIN_CONTROLLER_PID" 2>/dev/null || true
        wait "$RADWIN_CONTROLLER_PID" 2>/dev/null || true
        RADWIN_CONTROLLER_PID=""
    fi
}
_radwin_measure_exit() {
    local rc=$1 job
    _stop_radwin_controller
    if [ "$rc" -ne 0 ]; then
        # 同時計測の中断時だけ、その計測が起動した監視・送受信を片付ける。
        for job in $(jobs -pr); do kill -TERM "$job" 2>/dev/null || true; done
        for tx in Tx1 Tx2 Tx3; do
            docker exec "$tx" pkill -f 'iperf3|owd_sender.py' 2>/dev/null || true
        done
        for rx in Rx1 Rx2 Rx3; do
            docker exec "$rx" pkill -f 'iperf3|owd_receiver.py' 2>/dev/null || true
        done
    fi
}
if [ -n "${RADWIN_CONTROLLER_CSV:-}" ]; then
    python3 "$SCRIPT_DIR/radwin_wcmp_controller.py" --check
    trap '_radwin_measure_exit $?' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    setsid python3 -u "$SCRIPT_DIR/radwin_wcmp_controller.py" \
        --interval "${RADWIN_CONTROLLER_INTERVAL:-2}" \
        --log-csv "$RADWIN_CONTROLLER_CSV" > "${RADWIN_CONTROLLER_CSV%.csv}.log" 2>&1 &
    RADWIN_CONTROLLER_PID=$!
    echo "  [ok] 動的制御 PID=$RADWIN_CONTROLLER_PID / CSV: $RADWIN_CONTROLLER_CSV"
fi

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
    # throughput.csv は相対秒しか持たないため、t=0 の絶対時刻を残す。
    # これがないと controller.csv (絶対時刻) と重ね合わせられない。
    printf 'throughput_t0_epoch_ms=%s\nthroughput_t0_iso=%s\n' \
        "$t_start_ms" "$(date -Is)" > "$RESULTS_DIR/timebase.txt"
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

# ── 経路別の送信量モニター ──────────────────────────────────────────
# 2026-09-17 追加。マルチパスが実際にどの割合で分配したかを記録する。
# /proc/<pid>/net/dev の TX bytes (第10フィールド) をホストから直読みする。
PATH_CSV="$RESULTS_DIR/path_stats.csv"
echo "time,cr1_tx_bytes_per_sec,cr2_tx_bytes_per_sec,cr3_tx_bytes_per_sec" > "$PATH_CSV"
(
    set +e
    _t0=$(date +%s%3N); _tp=$_t0
    _get() {
        awk '$1=="leri-cr1:"{a=$10} $1=="leri-cr2:"{b=$10} $1=="leri-cr3:"{c=$10}
             END{printf "%.0f\n%.0f\n%.0f\n", a+0, b+0, c+0}' "$NETDEV_LERI" 2>/dev/null
    }
    { read -r p1; read -r p2; read -r p3; } < <(_get)
    p1=${p1:-0}; p2=${p2:-0}; p3=${p3:-0}
    while true; do
        sleep 1
        { read -r c1; read -r c2; read -r c3; } < <(_get)
        [[ "$c1" =~ ^[0-9]+$ && "$c2" =~ ^[0-9]+$ && "$c3" =~ ^[0-9]+$ ]] || continue
        _n=$(date +%s%3N); _t=$(( (_n - _t0) / 1000 )); _dt=$(( _n - _tp ))
        [ "$_dt" -le 0 ] && _dt=1000
        _d1=$(( (c1 - p1) * 1000 / _dt )); [ "$_d1" -lt 0 ] && _d1=0
        _d2=$(( (c2 - p2) * 1000 / _dt )); [ "$_d2" -lt 0 ] && _d2=0
        _d3=$(( (c3 - p3) * 1000 / _dt )); [ "$_d3" -lt 0 ] && _d3=0
        echo "$_t,$_d1,$_d2,$_d3" >> "$PATH_CSV"
        p1=$c1; p2=$c2; p3=$c3; _tp=$_n
    done
) &
PATH_MONITOR_PID=$!
echo "  [ok] 経路別モニター PID=$PATH_MONITOR_PID → $PATH_CSV"

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
        # operstate は UP のまま全パケット (データ + OSPF hello) を廃棄。
        #
        # netem は HTB の *葉* に付ける。root に付けると HTB を置き換えてしまい、
        # 解除時に HTB ごと消えてシェーピングが失われる (復旧後 t>=43 で CR1 が
        # CR1_BW を超過する現象の原因だった)。
        # 1:3 は HTB の default クラスでもあるため、fwmark の付かない
        # OSPF hello もここに落ちる → 隣接断が再現される。
        # 葉には既に pfifo (handle 11:/12:/13:) が居るため add では "File exists"
        # で失敗する。replace で同じハンドルを奪い、解除時に pfifo へ戻す。
        for _c in 1 2 3; do
            docker exec LER_Ingress tc qdisc replace dev leri-cr1 \
                parent "1:${_c}" handle "1${_c}:" netem loss 100% \
                || echo "  [NG] netem 注入に失敗: parent 1:${_c}"
        done
        sleep 20
        echo "[t=40s] leri-cr1 netem 解除 → 自然復旧 (HTB は保持)"
        # netem を消すだけだと葉が無くなり、既定 qdisc に置き換わってしまう。
        # 元の pfifo を limit ごと復元する。
        docker exec LER_Ingress tc qdisc replace dev leri-cr1 \
            parent 1:1 handle 11: pfifo limit "${PFIFO_LIMIT_HI:-1000}" || true
        docker exec LER_Ingress tc qdisc replace dev leri-cr1 \
            parent 1:2 handle 12: pfifo limit "${PFIFO_LIMIT_ME:-2000}" || true
        docker exec LER_Ingress tc qdisc replace dev leri-cr1 \
            parent 1:3 handle 13: pfifo limit "${PFIFO_LIMIT_LO:-4000}" || true
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
# 3クラスの起動を少しずらす。3クラス同時に -P 本ずつ接続すると
# サーバ側の accept キューが溢れ、"unable to read from stream socket" で
# クラスが丸ごと欠測する (2026-09-17/18 に -P 128 と -P 64 の両方で発生)。
# ずらしても計測窓には影響しない: 障害注入は壁時計のタイマーで行われるため、
# 送信開始が数百ms ずれても各クラスが障害を受ける瞬間は同じ。
IPERF_STAGGER="${IPERF_STAGGER:-0.7}"

docker exec Tx1 iperf3 -c 10.20.1.1 -p 1000 -u -b "$TX1_RATE" -l "${IPERF_DGRAM:-8950}" -P "${IPERF_STREAMS:-4}" -t "$DURATION" \
    -i 1 --get-server-output > "$RESULTS_DIR/iperf3_af41.log" 2>&1 &
PIDS="$!"
sleep "$IPERF_STAGGER"
docker exec Tx2 iperf3 -c 10.20.2.1 -p 2000 -u -b "$TX2_RATE" -l "${IPERF_DGRAM:-8950}" -P "${IPERF_STREAMS:-4}" -t "$DURATION" \
    -i 1 --get-server-output > "$RESULTS_DIR/iperf3_af42.log" 2>&1 &
PIDS="$PIDS $!"
sleep "$IPERF_STAGGER"
docker exec Tx3 iperf3 -c 10.20.3.1 -p 3000 -u -b "$TX3_RATE" -l "${IPERF_DGRAM:-8950}" -P "${IPERF_STREAMS:-4}" -t "$DURATION" \
    -i 1 --get-server-output > "$RESULTS_DIR/iperf3_af43.log" 2>&1 &
PIDS="$PIDS $!"

echo "  計測中... ${DURATION}秒待機"
# shellcheck disable=SC2086
wait $PIDS || true
echo "  計測完了"
if [ -n "$RADWIN_CONTROLLER_PID" ]; then
    if ! kill -0 "$RADWIN_CONTROLLER_PID" 2>/dev/null; then
        echo "[WARN] 動的コントローラが計測終了前に停止しました。controller.log を確認してください"
        # 呼び出し元が正常完了と誤認しないよう保存する。既存のログ回収は続行する。
        touch "${RADWIN_CONTROLLER_CSV%.csv}.failed"
    fi
    _stop_radwin_controller
fi

# OWD ログ回収 (受信プロセスが終了するまで最大7秒待機)
sleep 3
docker cp Rx1:/tmp/owd_af41.log "$RESULTS_DIR/owd_af41.log" 2>/dev/null || true
docker cp Rx2:/tmp/owd_af42.log "$RESULTS_DIR/owd_af42.log" 2>/dev/null || true
docker cp Rx3:/tmp/owd_af43.log "$RESULTS_DIR/owd_af43.log" 2>/dev/null || true
echo "  [ok] OWD ログ回収完了"

# ── 後処理 ────────────────────────────────────────────────────────────
[ -n "$FAILURE_PID" ] && { wait "$FAILURE_PID" 2>/dev/null || true; }
# netem が残っている場合は確実に削除して復旧。
# 葉に付けた netem を外す。HTB (root) は消さない。
# observe は netem を付けておらず、設定にも触らない約束なので何もしない。
if [ "$SCENARIO" != "observe" ]; then
docker exec LER_Ingress tc qdisc replace dev leri-cr1 \
    parent 1:1 handle 11: pfifo limit "${PFIFO_LIMIT_HI:-1000}" 2>/dev/null || true
docker exec LER_Ingress tc qdisc replace dev leri-cr1 \
    parent 1:2 handle 12: pfifo limit "${PFIFO_LIMIT_ME:-2000}" 2>/dev/null || true
docker exec LER_Ingress tc qdisc replace dev leri-cr1 \
    parent 1:3 handle 13: pfifo limit "${PFIFO_LIMIT_LO:-4000}" 2>/dev/null || true
# 旧方式 (root netem) の残骸があれば、それだけは root ごと外す
if docker exec LER_Ingress tc qdisc show dev leri-cr1 2>/dev/null \
     | grep -q "qdisc netem .* root"; then
    echo "  [warn] root netem の残骸を検出 → 削除。HTB の再適用が必要"
    docker exec LER_Ingress tc qdisc del dev leri-cr1 root 2>/dev/null || true
fi
fi
# failure_reroute: OSPF タイマーを基本設定 (frr_setup.sh: hello 1s / dead 3s) に戻す。
# 以前は "no ip ospf hello-interval" で FRR の既定値 (10s/40s) に戻しており、
# 一度 failure_reroute を実行すると leri-cr1 だけが基本設定と食い違っていた。
if [ "$SCENARIO" = "failure_reroute" ]; then
    docker exec frr-LER_Ingress vtysh -c "conf t" \
        -c "interface leri-cr1" \
        -c " ip ospf hello-interval 1" \
        -c " ip ospf dead-interval 3" 2>/dev/null || true
    docker exec frr-CR1 vtysh -c "conf t" \
        -c "interface cr1-leri" \
        -c " ip ospf hello-interval 1" \
        -c " ip ospf dead-interval 3" 2>/dev/null || true
fi

kill "$THR_MONITOR_PID"       2>/dev/null || true
kill "${DROP_MONITOR_PID:-}" 2>/dev/null || true
kill "${PATH_MONITOR_PID:-}" 2>/dev/null || true

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
# observe では常時動いている te_monitor を残す
[ "$SCENARIO" = "observe" ] || pkill -9 -f "frr_te_monitor.sh" > /dev/null 2>&1 || true

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

# observe (WCMP・1時間ごと) では plot_frr.py の図は使えない (単一経路前提) ので作らない
if [ "$SCENARIO" = "observe" ]; then
    echo "  (observe: 図は作らない)"
elif $PLOT_CMD "$PLOT_SCRIPT" --base "$FRR_BASE" --cr-mbps "$CR_MBPS"; then
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
if [[ "$SCENARIO" = "failure_reroute" || "$SCENARIO" = "manual" ]]; then
    # te_monitor のログを結果フォルダにも残す (/tmp は次の実行で上書きされる)
    cp /tmp/frr_te_monitor.log "$FRR_BASE/te_monitor.log" 2>/dev/null \
        && echo "  $FRR_BASE/te_monitor.log   # 迂回ログ (保存済み)" \
        || echo "  cat /tmp/frr_te_monitor.log   # 迂回ログ"
fi
