#!/bin/bash
# 角度・backoff 掃引の1点を記録する。長いコマンドを貼って改行で壊れないよう、短い形にした。
#
# 使い方:
#   sudo bash scripts/sweep_point.sh <ラベル> [読み取り回数=30]
#   例: sudo bash scripts/sweep_point.sh bo0_a-3
#       sudo bash scripts/sweep_point.sh check_a0_bo0 60
#
# 記録先: SWEEP_DIR。未指定なら results/frr/radwin/validation/ の中で
#         いちばん新しい *_running_* フォルダ (事前に mkdir しておく)。
#   <記録先>/sweep.csv          各点の中央値 (radwin_backoff_check.py の出力)
#   <記録先>/sweep_samples.csv  1回ごとの読み取り値
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

label="${1:-}"
rounds="${2:-30}"
[ -n "$label" ] || { echo "使い方: sudo bash scripts/sweep_point.sh <ラベル> [読み取り回数=30]  例: bo0_a-3" >&2; exit 1; }
[[ "$label" =~ ^[A-Za-z0-9_+.-]+$ ]] || { echo "ラベルは英数字と _ + - . だけにしてください: $label" >&2; exit 1; }
[[ "$rounds" =~ ^[1-9][0-9]*$ ]] || { echo "読み取り回数は正の整数: $rounds" >&2; exit 1; }

dir="${SWEEP_DIR:-$(ls -td "$LAB_DIR"/results/frr/radwin/validation/*_running_* 2>/dev/null | head -1 || true)}"
[ -n "$dir" ] && [ -d "$dir" ] || {
    echo "記録先のフォルダがありません。先に作ってください:" >&2
    echo "  mkdir -p results/frr/radwin/validation/$(date +%Y%m%d)_running_<目的>_01" >&2
    exit 1
}
csv="$dir/sweep.csv"
if [ -f "$csv" ] && cut -d, -f1 "$csv" | grep -qx -- "$label"; then
    echo "[注意] ラベル $label は記録済みです。追記します (同じ点の測り直しとして扱う)"
fi

echo "記録先: $csv   ラベル: $label   読み取り: ${rounds}回 (約$((rounds * 2))秒)"
start_epoch=$(date +%s)   # 判定は今回の実行分だけで行う (同じラベルの過去の記録を混ぜない)
python3 "$SCRIPT_DIR/radwin_backoff_check.py" --rounds "$rounds" --no-config --csv "$csv" --label "$label"

# この点の記録が乱れていないかを判定する。対象は角度を測る区間の受信側 (既定 .32)。
# 基準 (2026-09-28 の check1〜5 の実データで決めた):
#   ・標準偏差 2.0 dB 以下   … Lock ON で安定した状態でも .32 は約 3 dB 差の2値を交互にとり 1.3〜1.7 dB になる
#   ・前半と後半の中央値の差が 3 dB 未満 … 途中で状態が切り替わった記録 (Web UI 操作後など) を見つける
#   ・中央値から 6 dB 以上の落ち込みが 0 回 … 人の通過を見つける (60GHz は人体でほぼ遮られる)
# ほかの ODU に大きな落ち込みがあれば併記する (経路の近くで何か起きた手がかり)。
python3 - "$dir/sweep_samples.csv" "$label" "${SWEEP_ODU:-192.168.1.32}" "$start_epoch" <<'PY'
import csv, statistics as st, sys
path, label, odu, start = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
rows = [r for r in csv.DictReader(open(path)) if r["label"] == label and float(r["time"]) >= start]
def sig(ip):
    return [int(r["signal_dbm"]) for r in rows if r["odu"] == ip and r["signal_dbm"] not in ("", "None")]
s = sig(odu)
if len(s) < 5:
    print(f"\n[判定] {odu} の読み取りが {len(s)} 回しかない → 接続を確認して測り直し"); sys.exit()
med, sd, h = st.median(s), st.pstdev(s), len(s) // 2
shift = abs(st.median(s[:h]) - st.median(s[h:]))
dips = sum(v <= med - 6 for v in s)
ok = sd <= 2.0 and shift < 3 and dips == 0
print(f"\n[判定] {odu} 受信電力: 中央値 {med:g} dBm / 標準偏差 {sd:.1f} dB / 前半と後半の差 {shift:g} dB / "
      f"6dB以上の落ち込み {dips}回 → " + ("OK" if ok else "乱れあり。人の通過や Web UI の操作がなかったか確認し、同じラベルで測り直してください"))
others = []
for ip in sorted({r["odu"] for r in rows} - {odu}):
    o = sig(ip)
    if o:
        n = sum(v <= st.median(o) - 6 for v in o)
        if n:
            others.append(f"{ip} {n}回")
if others:
    print("       (参考) ほかの ODU の 6dB以上の落ち込み: " + " / ".join(others))
PY

# sudo で作ったファイルを実行したユーザーの持ち物に戻す (あとで手で編集・移動できるように)
if [[ "${SUDO_UID:-}" =~ ^[0-9]+$ ]]; then
    chown "$SUDO_UID:${SUDO_GID:-$SUDO_UID}" "$dir"/sweep*.csv 2>/dev/null || true
fi
