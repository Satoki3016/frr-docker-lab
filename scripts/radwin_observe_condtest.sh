#!/bin/bash
# 比較の条件 (P・S・N) の切り替えを veth で確かめる。1 本のコマンドで約 15 分。
#
#   sudo bash scripts/radwin_observe_condtest.sh
#
# 前提: veth のラボが起動済み (sudo bash scripts/frr_all_up.sh、LAB_MODE は付けない)、
#       te_monitor を止めてある (sudo pkill -f frr_te_monitor.sh)、ほかの観測が動いていない。
# 偽の ODU (MCS 9 → 制御の整形レート 1171M・重み 13) を使う。
#
# 確かめること (結果は観測フォルダの 04_control/state_*.csv と 06_system/events.csv):
#   C1  P の回: 整形レート 1171M、重み 13:100:100 のまま
#   C2  S の回: 制御が止まり、整形レート 2160M、重み 6:25:25 (te_monitor が固定の重みに書き直す)
#   C3  N の回: さらに te_monitor も止まり、経路表 6:25:25 のまま
#   C4  各回のあと: 1171M・重み 13 に戻り、止めた部品が起動し直す (再起動の回数には数えない)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ "$(id -u)" -eq 0 ] || { echo "sudo bash $0 として実行してください"; exit 1; }

python3 "$SCRIPT_DIR/radwin_fake_odu.py" 9 > /dev/null
env RADWIN_ALLOW_FAKE=1 python3 "$SCRIPT_DIR/radwin_observe.py" start \
    --purpose condtest --fake-odu-dir /tmp/radwin_fake_odu
OBS="$(cat /run/radwin/observe.dir)"
echo "[$(date +%T)] 開始時の計測が終わるのを待つ (約 3 分)"
sleep 200
for c in P S N; do
    echo "[$(date +%T)] 条件 $c"
    python3 "$SCRIPT_DIR/radwin_observe.py" fault --label none --condition "$c"
    sleep 40                                      # 元に戻ったことを記録に残す
done
python3 "$SCRIPT_DIR/radwin_observe.py" stop
echo "完了。観測フォルダ: ${OBS/_running_/_success_}"
