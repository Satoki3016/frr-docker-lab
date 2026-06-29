#!/bin/bash
# データ収集スクリプト
#
# 使い方:
#   bash scripts/measure.sh [duration] [normal|failure|failure_rsvp] [streams]
#
# シナリオ:
#   normal       (デフォルト) : 障害なし。全3リンクECMP+WRR優先制御
#   failure                  : t=20s に CoreRouter2:leri-cr2 ダウン、t=40s 復旧
#                              ECMPは静的のまま(障害リンク経由分は損失)
#   failure_rsvp             : t=20s に CoreRouter2:leri-cr2 ダウン、t=40s 復旧
#                              rsvp_monitor が障害検知→ECMPから除外→2リンクで継続
#
# 全シナリオ共通:
#   全3リンクにECMP分散、各リンクのWRR(4:2:1)が優先度制御
#   理論値: AF41=171Mbps, AF42=86Mbps, AF43=43Mbps (3リンク時)
#
# 例:
#   bash scripts/measure.sh 60 normal
#   bash scripts/measure.sh 60 failure
#   bash scripts/measure.sh 60 failure_rsvp
#   bash scripts/measure.sh 60 normal 81      # ストリーム数を81に変更

set -e
source "$(dirname "$0")/00_env.sh"
source "$(dirname "$0")/lab_config.sh"

DURATION=${1:-60}
SCENARIO=${2:-normal}
STREAMS=${3:-27}

# 引数バリデーション
if ! [[ "$DURATION" =~ ^[0-9]+$ ]]; then
    echo "[ERROR] 第1引数 (duration) は数値で指定してください: '$DURATION'"
    echo "使い方: bash $0 [duration] [normal|failure|failure_rsvp] [streams]"
    echo "例:     bash $0 60 normal"
    echo "例:     bash $0 60 failure 81"
    exit 1
fi
if ! [[ "$SCENARIO" =~ ^(normal|failure|failure_rsvp|failure_rsvp_v2)$ ]]; then
    echo "[ERROR] 第2引数 (scenario) は normal / failure / failure_rsvp / failure_rsvp_v2 のいずれかを指定してください: '$SCENARIO'"
    echo "使い方: bash $0 [duration] [normal|failure|failure_rsvp|failure_rsvp_v2] [streams]"
    exit 1
fi
if ! [[ "$STREAMS" =~ ^[0-9]+$ ]]; then
    echo "[ERROR] 第3引数 (streams) は数値で指定してください: '$STREAMS'"
    exit 1
fi

RESULTS_DIR="$LAB_DIR/results/$SCENARIO"
mkdir -p "$RESULTS_DIR"
PLOT_SCRIPT="$LAB_DIR/results/plot_rx.py"

echo "計測時間: ${DURATION}秒"
echo "シナリオ: ${SCENARIO}"
echo "ストリーム数: ${STREAMS}"
echo "結果保存先: $RESULTS_DIR"

# namespace が存在しない場合は自動セットアップ
if ! ip netns list | grep -q "LER_Ingress_ns"; then
    echo "=== namespace が未起動のため自動セットアップ ==="
    # 物理NICが利用可能か確認（NO-CARRIERならall-veth版を使用）
    _nic_ok=0
    for _nic in enp23s0f0np0 enp23s0f1np1; do
        if ip link show "$_nic" 2>/dev/null | grep -q "state UP"; then
            _nic_ok=1
            break
        fi
    done
    if [ "$_nic_ok" -eq 1 ]; then
        echo "  [物理NIC] enp* UP確認 → virttrx_setup.sh を使用"
        bash "$(dirname "$0")/virttrx_setup.sh"
    else
        echo "  [物理NIC] NO-CARRIER または未検出 → virttrx_setup_allveth.sh (全veth) を使用"
        bash "$(dirname "$0")/virttrx_setup_allveth.sh"
    fi
fi

echo ""
echo "=== QoS/ルーティング設定を再適用 ==="
bash "$(dirname "$0")/virttrx_tc.sh"  > /dev/null 2>&1
bash "$(dirname "$0")/60_rsvp_te.sh" > /dev/null 2>&1
echo "  virttrx_tc.sh / 60_rsvp_te.sh 適用完了"
echo "  CR1=${CR1_BW} CR2=${CR2_BW} CR3=${CR3_BW}"
echo "  ECMP: AF41→CR1+CR2+CR3, AF42→CR1+CR2+CR3, AF43→CR1+CR2+CR3"

# iperf3 確認
# ~/bin/iperf3 (静的バイナリ) があればそちらを優先
if [ -x "$HOME/bin/iperf3" ]; then
    export PATH="$HOME/bin:$PATH"
    export LD_LIBRARY_PATH="$HOME/bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
if ! which iperf3 &>/dev/null; then
    echo "[ERROR] iperf3 が見つかりません"
    echo "  開発マシン側で取得して転送してください:"
    echo "    apt-get download iperf3 libiperf0"
    echo "    dpkg-deb -x iperf3_*.deb /tmp/ex/ && dpkg-deb -x libiperf0_*.deb /tmp/ex/"
    echo "    scp /tmp/ex/usr/bin/iperf3 /tmp/ex/usr/lib/*/libiperf.so.0 admin@<switch>:~/bin/"
    exit 1
fi

# ----------------------------------------------------------------
# iperf3 サーバー起動
# ----------------------------------------------------------------
echo ""
echo "=== iperf3 サーバー起動 ==="
pkill -f "iperf3 -s -p 1000" 2>/dev/null || true
pkill -f "iperf3 -s -p 2000" 2>/dev/null || true
pkill -f "iperf3 -s -p 3000" 2>/dev/null || true
sleep 2
ip netns exec Rx1_ns iperf3 -s -p 1000 &
ip netns exec Rx2_ns iperf3 -s -p 2000 &
ip netns exec Rx3_ns iperf3 -s -p 3000 &
sleep 2
echo "  Rx1:1000, Rx2:2000, Rx3:3000 起動完了"

# ----------------------------------------------------------------
# OWD 受信プロセス起動 (port 5001/5002/5003, DSCP AF41/AF42/AF43)
# ----------------------------------------------------------------
# OWD プローブ用 DSCP マーキング (重複追加を防ぐため -C で確認)
for _rule in \
    "-p udp --dport 5001 -j DSCP --set-dscp-class AF41" \
    "-p udp --dport 5002 -j DSCP --set-dscp-class AF42" \
    "-p udp --dport 5003 -j DSCP --set-dscp-class AF43"; do
    ip netns exec LER_Ingress_ns iptables -t mangle -C PREROUTING $_rule 2>/dev/null || \
        ip netns exec LER_Ingress_ns iptables -t mangle -A PREROUTING $_rule
done
ip netns exec Rx1_ns python3 "$LAB_DIR/scripts/owd_receiver.py" \
    --port 5001 --duration "$DURATION" --out "$RESULTS_DIR/Tx1_owd.log" --label "Rx1-OWD" &
OWD_RX_PIDS="$!"
ip netns exec Rx2_ns python3 "$LAB_DIR/scripts/owd_receiver.py" \
    --port 5002 --duration "$DURATION" --out "$RESULTS_DIR/Tx2_owd.log" --label "Rx2-OWD" &
OWD_RX_PIDS="$OWD_RX_PIDS $!"
ip netns exec Rx3_ns python3 "$LAB_DIR/scripts/owd_receiver.py" \
    --port 5003 --duration "$DURATION" --out "$RESULTS_DIR/Tx3_owd.log" --label "Rx3-OWD" &
OWD_RX_PIDS="$OWD_RX_PIDS $!"
echo "  OWD受信: Rx1:5001(AF41) Rx2:5002(AF42) Rx3:5003(AF43) 起動完了"
sleep 0.3

# ----------------------------------------------------------------
# RSVP-TE モニター起動 (failure_rsvp のみ)
# ----------------------------------------------------------------
MONITOR_PID=""
MONITOR_LOG="$RESULTS_DIR/rsvp_monitor.log"
if [ "$SCENARIO" = "failure_rsvp" ] || [ "$SCENARIO" = "normal" ]; then
    bash "$(dirname "$0")/rsvp_monitor.sh" "$MONITOR_LOG" &
    MONITOR_PID=$!
    echo ""
    echo "  [RSVP-TE v1] ECMPモニター起動 PID=$MONITOR_PID (1s ポーリング)"
    sleep 1
elif [ "$SCENARIO" = "failure_rsvp_v2" ]; then
    bash "$(dirname "$0")/rsvp_monitor_v2.sh" "$MONITOR_LOG" &
    MONITOR_PID=$!
    echo ""
    echo "  [RSVP-TE v2] ECMPモニター起動 PID=$MONITOR_PID (イベント駆動 <1ms + NETEM_LIMIT=5)"
    sleep 1
fi

# ----------------------------------------------------------------
# 障害注入プロセス (failure / failure_rsvp)
# ----------------------------------------------------------------
FAILURE_PID=""
if [ "$SCENARIO" = "failure" ]; then
    # failure: HTB 内の leaf netem を loss 100% に変更するだけ (ip link set down は使わない)
    # → operstate=up のまま → RTNH_F_LINKDOWN フラグ未設定
    # → カーネルは ECMP で CR1 に 1/3 を送り続ける (カーネル自動FO が起きない)
    # → 各クラスの leaf netem が全パケットを破棄 → 実際に 1/3 がロス (ブラックホール)
    (
        sleep 20
        echo ""
        echo "[FAILURE] t=20s: leri-cr1 leaf netem → loss 100% (operstate=up のまま ECMP 継続)"
        ip netns exec LER_Ingress_ns tc qdisc change dev leri-cr1 parent 1:1 handle 11: netem loss 100%
        ip netns exec LER_Ingress_ns tc qdisc change dev leri-cr1 parent 1:2 handle 12: netem loss 100%
        ip netns exec LER_Ingress_ns tc qdisc change dev leri-cr1 parent 1:3 handle 13: netem loss 100%
        sleep 20
        echo "[RECOVER] t=40s: leri-cr1 leaf netem 復旧"
        ip netns exec LER_Ingress_ns tc qdisc change dev leri-cr1 parent 1:1 handle 11: netem delay "${CR1_DELAY:-0ms}" limit "${NETEM_LIMIT:-30}"
        ip netns exec LER_Ingress_ns tc qdisc change dev leri-cr1 parent 1:2 handle 12: netem delay "${DELAY_ME:-10ms}" limit "${NETEM_LIMIT:-30}"
        ip netns exec LER_Ingress_ns tc qdisc change dev leri-cr1 parent 1:3 handle 13: netem delay "${DELAY_LO:-40ms}" limit "${NETEM_LIMIT:-30}"
    ) &
    FAILURE_PID=$!
    echo "  障害注入: t=20s leri-cr1 leaf netem → loss 100% (operstate=up のまま ECMP 継続)"
    echo "  (failure: ルート変更なし → leri-cr1 経由の 1/3 が t=20-40s 間すべてブラックホール)"

elif [ "$SCENARIO" = "failure_rsvp" ] || [ "$SCENARIO" = "failure_rsvp_v2" ]; then
    # failure_rsvp / failure_rsvp_v2: ip link set down で operstate を変化させる
    # → RTNH_F_LINKDOWN フラグが立つ → rsvp_monitor(_v2) が operstate=down を検知
    # → ECMP を CR2+CR3 に再構築 + ingress police を 2 リンク分に縮小
    ip netns exec LER_Ingress_ns sysctl -qw net.ipv4.conf.leri-cr1.ignore_routes_with_linkdown=1
    echo "  [設定] leri-cr1: ignore_routes_with_linkdown=1 (rsvp_monitor に ECMP 再構築を委ねる)"
    (
        sleep 20
        echo ""
        echo "[FAILURE] t=20s: leri-cr1 リンクダウン (rsvp_monitor が検知→迂回)"
        ip netns exec LER_Ingress_ns ip link set leri-cr1 down
        sleep 20
        echo "[RECOVER] t=40s: leri-cr1 復旧"
        ip netns exec LER_Ingress_ns ip link set leri-cr1 up
        ip netns exec LER_Ingress_ns sysctl -qw net.ipv4.conf.leri-cr1.ignore_routes_with_linkdown=0
    ) &
    FAILURE_PID=$!
    if [ "$SCENARIO" = "failure_rsvp_v2" ]; then
        echo "  障害注入: t=20s leri-cr1 ダウン → rsvp_monitor_v2 が CR2+CR3 に即時迂回 (<1ms)"
    else
        echo "  障害注入: t=20s leri-cr1 ダウン → rsvp_monitor が CR2+CR3 に迂回"
    fi
fi

# ----------------------------------------------------------------
# スループットモニター起動
# ----------------------------------------------------------------
# 前回計測から残っているモニタプロセスを停止してから新しいものを起動する
# (停止しないと同一CSVに2つの時系列が混入してグラフがグチャグチャになる)
pkill -f "throughput_monitor.sh" 2>/dev/null || true
sleep 0.5

CSV_PATH="$RESULTS_DIR/throughput.csv"
if [ -f "$CSV_PATH" ] && [ ! -w "$CSV_PATH" ]; then
    echo "[ERROR] $CSV_PATH が書き込み不可: sudo rm $CSV_PATH"
    exit 1
fi
rm -f "$CSV_PATH" 2>/dev/null || true
bash "$(dirname "$0")/throughput_monitor.sh" "$RESULTS_DIR" &
THR_MONITOR_PID=$!

# ----------------------------------------------------------------
# 計測開始
# ----------------------------------------------------------------
echo ""
echo "=== 計測開始 (${DURATION}s) ==="

# ping: RTT計測
ip netns exec Tx1_ns ping -D -i 0.1 -w "$DURATION" 10.20.1.1 \
    > "$RESULTS_DIR/Tx1_ping.log" 2>&1 &
PIDS="$!"
ip netns exec Tx2_ns ping -D -i 0.1 -w "$DURATION" 10.20.2.1 \
    > "$RESULTS_DIR/Tx2_ping.log" 2>&1 &
PIDS="$PIDS $!"
ip netns exec Tx3_ns ping -D -i 0.1 -w "$DURATION" 10.20.3.1 \
    > "$RESULTS_DIR/Tx3_ping.log" 2>&1 &
PIDS="$PIDS $!"

# OWD: 片道遅延プローブ (50pps, DSCPマーク付き)
ip netns exec Tx1_ns python3 "$LAB_DIR/scripts/owd_sender.py" \
    --dst 10.20.1.1 --port 5001 --dscp 34 --interval 0.02 --duration "$DURATION" --label "Tx1-OWD" &
PIDS="$PIDS $!"
ip netns exec Tx2_ns python3 "$LAB_DIR/scripts/owd_sender.py" \
    --dst 10.20.2.1 --port 5002 --dscp 36 --interval 0.02 --duration "$DURATION" --label "Tx2-OWD" &
PIDS="$PIDS $!"
ip netns exec Tx3_ns python3 "$LAB_DIR/scripts/owd_sender.py" \
    --dst 10.20.3.1 --port 5003 --dscp 38 --interval 0.02 --duration "$DURATION" --label "Tx3-OWD" &
PIDS="$PIDS $!"

# iperf3: UDP スループット計測
echo "  Tx1 rate=${TX1_RATE}  Tx2 rate=${TX2_RATE}  Tx3 rate=${TX3_RATE}  streams=${STREAMS}"
ip netns exec Tx1_ns iperf3 -c 10.20.1.1 -p 1000 -u -b "$TX1_RATE" -l 1400 -P "$STREAMS" \
    -t "$DURATION" 2>&1 &
PIDS="$PIDS $!"
ip netns exec Tx2_ns iperf3 -c 10.20.2.1 -p 2000 -u -b "$TX2_RATE" -l 1400 -P "$STREAMS" \
    -t "$DURATION" 2>&1 &
PIDS="$PIDS $!"
ip netns exec Tx3_ns iperf3 -c 10.20.3.1 -p 3000 -u -b "$TX3_RATE" -l 1400 -P "$STREAMS" \
    -t "$DURATION" 2>&1 &
PIDS="$PIDS $!"

echo "計測中... ${DURATION}秒待機"
# shellcheck disable=SC2086
wait $PIDS || true
echo "計測完了"

# 障害リンク確実復旧
if [ -n "$FAILURE_PID" ]; then
    wait "$FAILURE_PID" 2>/dev/null || true
    ip netns exec LER_Ingress_ns ip link set leri-cr1 up 2>/dev/null || true
fi

kill "$THR_MONITOR_PID" 2>/dev/null || true

# OWD 受信プロセス停止 & iptables クリーンアップ
# shellcheck disable=SC2086
kill $OWD_RX_PIDS 2>/dev/null || true
for _rule in \
    "-p udp --dport 5001 -j DSCP --set-dscp-class AF41" \
    "-p udp --dport 5002 -j DSCP --set-dscp-class AF42" \
    "-p udp --dport 5003 -j DSCP --set-dscp-class AF43"; do
    ip netns exec LER_Ingress_ns iptables -t mangle -D PREROUTING $_rule 2>/dev/null || true
done

if [ -n "$MONITOR_PID" ]; then
    kill "$MONITOR_PID" 2>/dev/null || true
    echo "  [RSVP-TE] モニター停止: ログ→ $MONITOR_LOG"
fi

# サーバー停止 (ホストプロセスとして動作しているため pkill で停止)
pkill -f "iperf3 -s -p 1000" 2>/dev/null || true
pkill -f "iperf3 -s -p 2000" 2>/dev/null || true
pkill -f "iperf3 -s -p 3000" 2>/dev/null || true

sleep 1
cat /tmp/rx1_server.json > "$RESULTS_DIR/Rx1_server.json" 2>/dev/null || true
cat /tmp/rx2_server.json > "$RESULTS_DIR/Rx2_server.json" 2>/dev/null || true
cat /tmp/rx3_server.json > "$RESULTS_DIR/Rx3_server.json" 2>/dev/null || true

echo ""
echo "=== 収集ファイル ==="
ls -lh "$RESULTS_DIR"/*.csv "$RESULTS_DIR"/*.log 2>/dev/null || true

echo ""
echo "=== 計測完了 ==="
echo "結果: $RESULTS_DIR"

echo ""
echo "=== パケットロス統計 ==="
bash "$(dirname "$0")/packet_loss.sh" "$RESULTS_DIR"

echo ""
echo "=== グラフ生成 ==="
# sudo 実行時は結果ファイルのオーナーを一般ユーザーに変更
if [ -n "$SUDO_USER" ]; then
    chown -R "$SUDO_USER:$SUDO_USER" "$RESULTS_DIR" 2>/dev/null || true
fi
# グラフ生成は一般ユーザーとして実行 (sudo 時は sudo -u)
if [ -n "$SUDO_USER" ]; then
    PLOT_CMD="sudo -u $SUDO_USER python3"
else
    PLOT_CMD="python3"
fi
if $PLOT_CMD "$PLOT_SCRIPT" "$RESULTS_DIR"; then
    echo "グラフ保存先: $RESULTS_DIR"
else
    echo "[WARN] グラフ生成失敗: python3 $PLOT_SCRIPT $RESULTS_DIR"
fi

# 3シナリオ全揃っていれば比較グラフも自動生成
RESULTS_BASE="$LAB_DIR/results"
if [ -f "$RESULTS_BASE/failure/throughput.csv" ] && \
   [ -f "$RESULTS_BASE/failure_rsvp/throughput.csv" ] && \
   [ -f "$RESULTS_BASE/normal/throughput.csv" ]; then
    echo ""
    echo "=== 3シナリオ比較グラフ生成 ==="
    if $PLOT_CMD "$PLOT_SCRIPT" "$RESULTS_BASE"; then
        echo "比較グラフ: $RESULTS_BASE/compare_all_scenarios.png"
    fi
fi
