#!/bin/bash
# physical2_frr_measure_sw2.sh
# SW2で実行: iperf3/OWDサーバ起動 + スループット計測
#
# 使い方:
#   sudo bash /home/admin/scripts/physical2_frr_measure_sw2.sh [duration] [normal|failure|failure_reroute]
#
# SW1のphysical2_frr_measure_sw1.shより先に起動すること

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DURATION=${1:-60}
SCENARIO=${2:-normal}
RESULTS_DIR="/tmp/frr_results_${SCENARIO}"

if ! [[ "$DURATION" =~ ^[0-9]+$ ]]; then
    echo "[ERROR] durationは数値で指定してください: '$DURATION'"
    exit 1
fi

# 前回の残骸をクリーンアップ（自分自身・親プロセスは除外）
for pid in $(pgrep -f "physical2_frr_measure_sw2" 2>/dev/null); do
    [ "$pid" = "$$" ] || [ "$pid" = "$PPID" ] || kill -9 "$pid" 2>/dev/null || true
done
for c in Rx1 Rx2 Rx3; do
    docker exec "$c" pkill -9 -f iperf3 2>/dev/null || true
    docker exec "$c" pkill -9 -f owd_receiver 2>/dev/null || true
done
sleep 1
if ! [[ "$SCENARIO" =~ ^(normal|failure|failure_reroute)$ ]]; then
    echo "[ERROR] シナリオは normal / failure / failure_reroute のいずれか"
    exit 1
fi

mkdir -p "$RESULTS_DIR"

echo "████████████████████████████████████████"
echo "  SW2 計測準備 [${SCENARIO}] ${DURATION}s"
echo "████████████████████████████████████████"
echo "  結果保存先: $RESULTS_DIR"

# 前プロセスをクリーンアップ (SIGKILL で確実に停止)
for rx in Rx1 Rx2 Rx3; do
    docker exec "$rx" pkill -9 -f "iperf3"       2>/dev/null || true
    docker exec "$rx" pkill -9 -f "owd_receiver" 2>/dev/null || true
done
# iperf3プロセス消滅を確認 (最大3秒待機)
for rx in Rx1 Rx2 Rx3; do
    for i in $(seq 1 10); do
        if ! docker exec "$rx" pgrep -f iperf3 >/dev/null 2>&1; then
            break
        fi
        sleep 0.3
    done
done
sleep 1

# owd_receiver.py をコンテナへコピー
for rx in Rx1 Rx2 Rx3; do
    docker cp "${SCRIPT_DIR}/owd_receiver.py" "${rx}:/tmp/owd_receiver.py"
done

# iperf3 サーバー起動: AF41→Rx1:5101, AF42→Rx2:2000, AF43→Rx3:3000
# クラスごとに異なるRxコンテナで受信 (同一Rxへの集約による資源競合を回避)
for entry in "Rx1:5101" "Rx2:2000" "Rx3:3000"; do
    rx="${entry%%:*}"
    port="${entry##*:}"
    # 既存プロセスをポート単位でも念入りに停止
    docker exec "$rx" sh -c "ss -lntp | grep ':${port} ' | awk '{print \$6}' | grep -oP 'pid=\K[0-9]+' | xargs -r kill -9" 2>/dev/null || true
    sleep 0.3
    # 最大3回リトライ
    ok=0
    for try in 1 2 3; do
        docker exec -d "$rx" iperf3 -s -p "$port"
        for i in $(seq 1 10); do
            if docker exec "$rx" sh -c "ss -lnt | grep -q :${port}"; then
                ok=1; break 2
            fi
            sleep 0.5
        done
        echo "  [retry ${try}] ${rx}:${port} not ready, retrying..."
        docker exec "$rx" pkill -9 -f "iperf3 -s -p ${port}" 2>/dev/null || true
        sleep 1
    done
    if [ "$ok" -eq 1 ]; then
        echo "  [ok] ${rx} iperf3 listening on port ${port}"
    else
        echo "  [warn] ${rx}:${port} not confirmed — proceeding anyway"
    fi
    sleep 0.5
done

# OWD 受信プロセス起動 (DURATION+20秒のバッファ)
docker exec -d Rx1 python3 /tmp/owd_receiver.py --port 5001 \
    --duration "$(( DURATION + 20 ))" --out /tmp/owd_af41.log --label "AF41"
docker exec -d Rx2 python3 /tmp/owd_receiver.py --port 5002 \
    --duration "$(( DURATION + 20 ))" --out /tmp/owd_af42.log --label "AF42"
docker exec -d Rx3 python3 /tmp/owd_receiver.py --port 5003 \
    --duration "$(( DURATION + 20 ))" --out /tmp/owd_af43.log --label "AF43"
echo "  [ok] OWD 受信プロセス (Rx1:5001 / Rx2:5002 / Rx3:5003)"

# スループットモニター起動 (LER_Egress → Rx方向 TX bytes)
CSV_PATH="${RESULTS_DIR}/throughput.csv"
rm -f "$CSV_PATH"
echo "time,rx1_bytes_per_sec,rx2_bytes_per_sec,rx3_bytes_per_sec" > "$CSV_PATH"

LER_EGRESS_PID=$(docker inspect --format '{{.State.Pid}}' LER_Egress)
NETDEV_FILE="/proc/${LER_EGRESS_PID}/net/dev"
echo "  [ok] スループットモニター (LER_Egress PID=${LER_EGRESS_PID}) → ${CSV_PATH}"

(
    set +e
    t_start_ms=$(date +%s%3N)
    t_prev_ms=$t_start_ms
    get_bytes() {
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
) < /dev/null > /dev/null 2>&1 &
THR_MONITOR_PID=$!

echo ""
echo "████ SW2 準備完了 ━━ 今すぐSW1スクリプトを起動してください ████"
echo ""
echo "  【SW1で実行】:"
echo "  sudo bash /home/kannolab/scripts/physical2_frr_measure_sw1.sh ${DURATION} ${SCENARIO}"
echo ""
echo "  ${DURATION}秒 + 余裕(20s) 待機中..."

# DURATION + 20秒待機 (SW1クライアントが終了するまで余裕を持つ)
sleep "$(( DURATION + 20 ))"

# OWD ログ回収
sleep 3
docker cp Rx1:/tmp/owd_af41.log "${RESULTS_DIR}/owd_af41.log" 2>/dev/null \
    && echo "  [ok] owd_af41.log" || echo "  [warn] owd_af41.log なし"
docker cp Rx2:/tmp/owd_af42.log "${RESULTS_DIR}/owd_af42.log" 2>/dev/null \
    && echo "  [ok] owd_af42.log" || echo "  [warn] owd_af42.log なし"
docker cp Rx3:/tmp/owd_af43.log "${RESULTS_DIR}/owd_af43.log" 2>/dev/null \
    && echo "  [ok] owd_af43.log" || echo "  [warn] owd_af43.log なし"

# クリーンアップ (SIGTERM → SIGKILL でサブシェル+子プロセスを確実に終了)
kill "$THR_MONITOR_PID" 2>/dev/null || true
sleep 0.5
kill -9 "$THR_MONITOR_PID" 2>/dev/null || true
pkill -9 -P "$THR_MONITOR_PID" 2>/dev/null || true
wait "$THR_MONITOR_PID" 2>/dev/null || true
for rx in Rx1 Rx2 Rx3; do
    timeout 5 docker exec "$rx" pkill -9 -f "iperf3"       2>/dev/null || true
    timeout 5 docker exec "$rx" pkill -9 -f "owd_receiver" 2>/dev/null || true
done

echo ""
echo "████████████████████████████████████████"
echo "  SW2 計測完了: $RESULTS_DIR"
echo "████████████████████████████████████████"
echo ""
ls -lh "${RESULTS_DIR}/" 2>/dev/null || true
echo ""
echo "■ 結果ファイルは all.sh が自動転送します (EXP_TAG サブディレクトリ配下に保存):"
echo "  保存先例: results/frr/<EXP_TAG>/frr_${SCENARIO}/"
echo "  手動転送する場合:"
echo "    scp kannolab@192.168.128.1:${RESULTS_DIR}/*.csv \\"
echo "        kannolab@192.168.128.1:${RESULTS_DIR}/*.log \\"
echo "        /home/kannolab/デスクトップ/Ichikawa_projects/frr-docker-lab-main2/results/frr/<EXP_TAG>/frr_${SCENARIO}/"
