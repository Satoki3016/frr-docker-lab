#!/bin/bash
# 雨の観測 (radwin_observe.py) を veth で確かめる。1 本のコマンドで約 2 時間 10 分。
#
#   sudo bash scripts/radwin_observe_vethtest.sh
#
# 前提: veth のラボが起動済み (sudo bash scripts/frr_all_up.sh、LAB_MODE は付けない)、
#       te_monitor を止めてある (sudo pkill -f frr_te_monitor.sh)。
# 偽の ODU を使うので、実機 (c2) では radwin_observe.py が拒否する。
#
# 確かめること (結果は観測フォルダの events.csv / probes.csv / state_*.csv / check.txt):
#   V1  2 時間動かして、記録の空白がない
#   V2  容量低下 (MCS 9 → 3) と無線断で追加の計測が起き、10 分ごとに続き、戻ったら止まる
#   V3  計測の前後で HTB の整形レートと重みが変わらない
#   V4  計測のあいだ軽い負荷が止まり、終わると再開する
#   V5  記録係を強制的に止めると、監督役が起動し直す
# 操作の時刻は観測フォルダの vethtest_marks.csv に残す。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ "$(id -u)" -eq 0 ] || { echo "sudo bash $0 として実行してください"; exit 1; }

MARKS=""
mark() {   # 操作の時刻を記録して表示する
    echo "[$(date +%T)] $1"
    [ -z "$MARKS" ] || printf '%s,%s\n' "$(date +%s)" "$1" >> "$MARKS"
}
wait_min() { mark "待機 $1 分 ($2)"; sleep $(( $1 * 60 )); }
fake() { python3 "$SCRIPT_DIR/radwin_fake_odu.py" "$1" > /dev/null; mark "偽の ODU: $1"; }

T0=$(date +%s)
python3 "$SCRIPT_DIR/radwin_fake_odu.py" 9 > /dev/null
env RADWIN_ALLOW_FAKE=1 python3 "$SCRIPT_DIR/radwin_observe.py" start \
    --purpose vethtest --fake-odu-dir /tmp/radwin_fake_odu
OBS="$(cat /run/radwin/observe.dir)"
MARKS="$OBS/vethtest_marks.csv"
echo "time,mark" > "$MARKS"
mark "開始 (偽の ODU: 9)"

wait_min 10 "開始時の計測と、平常の記録"
fake 3                                   # V2: 容量低下 → すぐ計測、10 分ごとに繰り返す
wait_min 25 "容量低下が続く"
fake 9                                   # V2: 回復 → 1 回計測して、繰り返しが止まる
wait_min 15 "回復後"
fake down                                # V2: 無線断 → 重み 0 で CR1 が外れ、計測
wait_min 15 "無線断が続く"
fake 9
wait_min 5 "無線断からの回復"
pkill -f radwin_odu_logger.py && mark "V5: odu_logger を強制終了"   # V5
# 残りは平常のまま、開始から 2 時間 10 分まで (15 分ごとの計測が入る)
REST=$(( T0 + 130 * 60 - $(date +%s) ))
(( REST > 0 )) && { mark "待機 $(( REST / 60 )) 分 (平常。15 分ごとの計測)"; sleep "$REST"; }
mark "停止"
python3 "$SCRIPT_DIR/radwin_observe.py" stop
echo "完了。上に表示された検査結果 (check.txt) の場所を Claude に伝えてください"
