#!/bin/bash
# 無線が「途切れては戻る」障害を veth で起こし、P3 と P4 (戻すのを待つ) を比べる。約 15 分。
#
#   sudo bash scripts/radwin_observe_flaptest.sh            # P3 と P4 を比べる
#   sudo bash scripts/radwin_observe_flaptest.sh P P4       # ほかの 2 条件でもよい
#   sudo bash scripts/radwin_observe_flaptest.sh P3 P4 2    # 回数を 2 回ずつに (約 6 分)
#
# 前提: veth のラボが起動済み (sudo bash scripts/frr_all_up.sh、LAB_MODE は付けない)、
#       te_monitor を止めてある (sudo pkill -f frr_te_monitor.sh)、ほかの観測が動いていない。
#
# 実機 (2026-10-12 stand30) では、人が立つと無線が数秒おきに途切れては戻り、OSPF の隣接も
# そのたびに消えては戻った。ここでは CR1─LER_Egress の間で、両方向の受信をすべて捨てる
# (tc の ingress で matchall drop) ことで同じ状態を作る。リンクは up のまま通信だけ止まるので、
# 無線と同じく BFD (約 0.9 秒) が隣接を落とす。止めている間は偽の ODU を MCS 1 にする。
#
# 1 回の流れ: 60 秒の全負荷計測の、通信の開始から 15 秒後に「3 秒止める・4 秒通す」を 5 回。
# 比べるもの (観測フォルダの集計):
#   - 遮られた区間の AF41 の損失 [個/秒] (P4 は戻すのを待つので小さくなる見込み)
#   - te_monitor.log: P4 では「安定するまで経路へ戻さない」が出て、途切れの間は CR1 が戻らない
#   - route_state.csv: 止めている間、CR1 が LER_Egress 行きを LER_Ingress へ送り返す (cr1-leri)
#   - rx_drops.csv: 受信側の取りこぼし (udp.RcvbufErrors) の有無
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ "$(id -u)" -eq 0 ] || { echo "sudo bash $0 として実行してください"; exit 1; }
CONDS=("${1:-P3}" "${2:-P4}")

# 止める・通す。prio 7 の filter だけを足し消しする (ほかの設定には触れない)
block() {
    for spec in "LER_Egress lere-cr1" "CR1 cr1-lere"; do
        set -- $spec
        docker exec "$1" tc qdisc add dev "$2" handle ffff: ingress 2>/dev/null || true
        docker exec "$1" tc filter add dev "$2" parent ffff: prio 7 matchall action drop
    done
    python3 "$SCRIPT_DIR/radwin_fake_odu.py" 1 > /dev/null
}
unblock() {
    for spec in "LER_Egress lere-cr1" "CR1 cr1-lere"; do
        set -- $spec
        docker exec "$1" tc filter del dev "$2" parent ffff: prio 7 2>/dev/null || true
    done
    python3 "$SCRIPT_DIR/radwin_fake_odu.py" 9 > /dev/null
}
trap unblock EXIT

unblock
env RADWIN_ALLOW_FAKE=1 python3 "$SCRIPT_DIR/radwin_observe.py" start \
    --purpose flaptest --fake-odu-dir /tmp/radwin_fake_odu --probe-seconds 60 --no-start-probe
OBS="$(cat /run/radwin/observe.dir)"
MARKS="$OBS/06_system/flaptest_marks.csv"
echo "time,mark" > "$MARKS"
mark() { echo "[$(date +%T)] $1"; printf '%s,%s\n' "$(date +%s.%N)" "$1" >> "$MARKS"; }
echo "[$(date +%T)] 制御が最初の整形レートと重みを書くのを待つ (20 秒)"
sleep 20

for round in $(seq 1 "${3:-5}"); do
    for c in "${CONDS[@]}"; do
        mark "round$round $c 計測を依頼"
        python3 "$SCRIPT_DIR/radwin_observe.py" fault --label flap --condition "$c" &
        FPID=$!
        start=$(date +%s)
        until ls "$OBS"/02_fullload/*_running_*/frr_observe/timebase.txt 2>/dev/null \
              | xargs -r stat -c %Y 2>/dev/null | awk -v s="$start" '$1>=s{f=1} END{exit !f}'; do
            sleep 1
        done
        sleep 15
        for k in 1 2 3 4 5; do
            block;   mark "round$round $c 止めた ($k)";  sleep 3
            unblock; mark "round$round $c 通した ($k)";  sleep 4
        done
        wait "$FPID"
        sleep 5
    done
done
python3 "$SCRIPT_DIR/radwin_observe.py" stop
echo "完了。観測フォルダ: ${OBS/_running_/_success_}"
