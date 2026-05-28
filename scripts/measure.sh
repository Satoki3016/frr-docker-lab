#!/bin/bash
# データ収集スクリプト
#
# 使い方:
#   bash scripts/measure.sh [duration] [normal|failure|failure_rsvp]
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

set -e
source "$(dirname "$0")/00_env.sh"
source "$(dirname "$0")/lab_config.sh"

DURATION=${1:-60}
SCENARIO=${2:-normal}

# namespace が存在しない場合は自動セットアップ
if ! ip netns list | grep -q "LER_Ingress_ns"; then
    echo "=== namespace が未起動のため自動セットアップ ==="
    bash "$(dirname "$0")/virttrx_setup.sh"
fi

RESULTS_DIR="$LAB_DIR/results/$SCENARIO"
mkdir -p "$RESULTS_DIR"

PLOT_SCRIPT="$LAB_DIR/results/plot_rx.py"

echo "計測時間: ${DURATION}秒"
echo "シナリオ: ${SCENARIO}"
echo "結果保存先: $RESULTS_DIR"

# ----------------------------------------------------------------
# QoS・ルーティング設定を再適用
# ----------------------------------------------------------------
echo ""
echo "=== QoS/ルーティング設定を再適用 ==="
bash "$(dirname "$0")/virttrx_tc.sh"  > /dev/null 2>&1
bash "$(dirname "$0")/60_rsvp_te.sh" > /dev/null 2>&1
echo "  30_tc.sh / 60_rsvp_te.sh 適用完了"
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
# RSVP-TE モニター起動 (failure_rsvp のみ)
# ----------------------------------------------------------------
MONITOR_PID=""
MONITOR_LOG="$RESULTS_DIR/rsvp_monitor.log"
if [ "$SCENARIO" = "failure_rsvp" ] || [ "$SCENARIO" = "normal" ]; then
    bash "$(dirname "$0")/rsvp_monitor.sh" "$MONITOR_LOG" &
    MONITOR_PID=$!
    echo ""
    echo "  [RSVP-TE] ECMPモニター起動 PID=$MONITOR_PID (ingress police を動的管理)"
    sleep 1
fi

# ----------------------------------------------------------------
# 障害注入プロセス (failure / failure_rsvp)
# ----------------------------------------------------------------
FAILURE_PID=""
if [ "$SCENARIO" = "failure" ] || [ "$SCENARIO" = "failure_rsvp" ]; then
    (
        sleep 20
        echo ""
        echo "[FAILURE] t=20s: LER_Ingress leri-cr1 ダウン (AF41 PRIMARY LSP 切断)"
        ip netns exec LER_Ingress_ns ip link set leri-cr1 down
        sleep 20
        echo "[RECOVER] t=40s: LER_Ingress leri-cr1 復旧"
        ip netns exec LER_Ingress_ns ip link set leri-cr1 up
    ) &
    FAILURE_PID=$!
    echo ""
    echo "  障害注入: t=20s leri-cr1ダウン(AF41 PRIMARY), t=40s 復旧"
    if [ "$SCENARIO" = "failure" ]; then
        echo "  (failure: 静的経路のまま → AF41 は t=20-40s 間スループット 0)"
    else
        echo "  (failure_rsvp: MPLS-TE FRR → AF41 は残存リンク(CR2+CR3)に迂回、ingress police も更新し優先度制御継続)"
    fi
fi

# ----------------------------------------------------------------
# スループットモニター起動
# ----------------------------------------------------------------
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

# iperf3: UDP スループット計測
# -P 3: 並列3ストリームで異なる送信元ポート → ECMP で3リンク全てに分散
echo "  Tx1 rate=${TX1_RATE}  Tx2 rate=${TX2_RATE}  Tx3 rate=${TX3_RATE}"
ip netns exec Tx1_ns iperf3 -c 10.20.1.1 -p 1000 -u -b "$TX1_RATE" -l 1400 -P 9 \
    -t "$DURATION" 2>&1 &
PIDS="$PIDS $!"
ip netns exec Tx2_ns iperf3 -c 10.20.2.1 -p 2000 -u -b "$TX2_RATE" -l 1400 -P 9 \
    -t "$DURATION" 2>&1 &
PIDS="$PIDS $!"
ip netns exec Tx3_ns iperf3 -c 10.20.3.1 -p 3000 -u -b "$TX3_RATE" -l 1400 -P 9 \
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
if python3 "$PLOT_SCRIPT" "$RESULTS_DIR"; then
    echo "グラフ保存先: $RESULTS_DIR"
else
    echo "[WARN] グラフ生成失敗: python3 $PLOT_SCRIPT $RESULTS_DIR"
fi
