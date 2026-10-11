#!/bin/bash
# 改良版 P′ (条件 P2) と今の方式 (P) を、veth で同じ「容量の低下」を起こして比べる。約 50 分。
#
#   sudo bash scripts/radwin_observe_pprimetest.sh
#
# 前提: veth のラボが起動済み (sudo bash scripts/frr_all_up.sh、LAB_MODE は付けない)、
#       te_monitor を止めてある (sudo pkill -f frr_te_monitor.sh)、ほかの観測が動いていない。
#
# 1 回の流れ: 全負荷計測を始め、通信の開始から約 40 秒後に偽の ODU を MCS 9 → 1 に下げ
# (制御が整形レートを 1171 → 180M、重みを 13 → 2 に下げる)、30 秒後に MCS 9 に戻す。
# P と P2 を交互に 5 回ずつ。
# MCS 1 にするのは、P の隙間で AF41 が溢れる条件を作るため。整形 180M では AF41 の上限が
# 約 172M で、CR1 に AF41 が 2 本 (250M) 乗れば溢れる (重み 13 で 2 本以上になる確率 約 9 割)。
# MCS 3 (整形 450M) では 4 本以上が要り、2026-10-12 の 3 回ずつの試験では P でも溢れなかった。
# 比べるもの (観測フォルダの集計で見る):
#   - LER_Ingress の leri-cr1 で落ちた AF41 (P は HTB を先に絞るので溢れる、P2 は経路が先なので溢れない見込み)
#   - HTB を下げた時刻と、経路の重みが変わった時刻の差 (controller.log / te_monitor.log)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ "$(id -u)" -eq 0 ] || { echo "sudo bash $0 として実行してください"; exit 1; }

python3 "$SCRIPT_DIR/radwin_fake_odu.py" 9 > /dev/null
env RADWIN_ALLOW_FAKE=1 python3 "$SCRIPT_DIR/radwin_observe.py" start \
    --purpose pprimetest --fake-odu-dir /tmp/radwin_fake_odu
OBS="$(cat /run/radwin/observe.dir)"
MARKS="$OBS/06_system/pprimetest_marks.csv"
echo "time,mark" > "$MARKS"
mark() { echo "[$(date +%T)] $1"; printf '%s,%s\n' "$(date +%s.%N)" "$1" >> "$MARKS"; }
echo "[$(date +%T)] 開始時の計測が終わるのを待つ (約 3 分)"
sleep 200

for round in 1 2 3 4 5; do
    for c in P P2; do
        mark "round$round $c 計測を依頼"
        python3 "$SCRIPT_DIR/radwin_observe.py" fault --label degrade --condition "$c" &
        FPID=$!
        # 通信の開始 (計測フォルダに timebase.txt ができる) を待ってから 40 秒後に下げる
        start=$(date +%s)
        until ls "$OBS"/02_fullload/*_running_*/frr_observe/timebase.txt 2>/dev/null \
              | xargs -r stat -c %Y 2>/dev/null | awk -v s="$start" '$1>=s{f=1} END{exit !f}'; do
            sleep 1
        done
        sleep 40
        python3 "$SCRIPT_DIR/radwin_fake_odu.py" 1 > /dev/null; mark "round$round $c MCS 1 に下げた"
        sleep 30
        python3 "$SCRIPT_DIR/radwin_fake_odu.py" 9 > /dev/null; mark "round$round $c MCS 9 に戻した"
        wait "$FPID"
        sleep 30                                   # 元に戻ったことを記録に残す
    done
done
python3 "$SCRIPT_DIR/radwin_observe.py" stop
echo "完了。観測フォルダ: ${OBS/_running_/_success_}"
