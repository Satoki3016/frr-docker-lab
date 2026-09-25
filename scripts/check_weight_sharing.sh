#!/bin/bash
# 動的制御 ↔ frr_te_monitor の重み共有 (案A) の状態を1画面に表示する。読み取り専用。
# 使い方:
#   sudo watch -n1 bash scripts/check_weight_sharing.sh
#   sudo bash scripts/check_weight_sharing.sh          # 1回だけ
WEIGHTS_FILE="${RADWIN_WEIGHTS_FILE:-/run/radwin/weights.env}"
TE_PID_FILE="${RADWIN_TE_PID_FILE:-/run/radwin/te_monitor.pid}"
LOG_FILE="${1:-/tmp/frr_te_monitor.log}"

echo "── te_monitor ─────────────────────────────"
pid=$(cat "$TE_PID_FILE" 2>/dev/null)
if [ -z "$pid" ]; then
    echo "pidfile: なし"
elif [ -d "/proc/$pid" ]; then
    echo "pidfile: PID=$pid (稼働中: $(tr '\0' ' ' < "/proc/$pid/cmdline"))"
else
    echo "pidfile: PID=$pid (プロセスなし ← 強制終了の残骸)"
fi
# pgrep 自身やこのスクリプトを数えないよう、/proc の argv で数える
n=0
for d in /proc/[0-9]*; do
    mapfile -d '' -t a < "$d/cmdline" 2>/dev/null || continue
    [ "${#a[@]}" -ge 2 ] || continue
    case "${a[0]##*/}" in bash|sh) ;; *) continue ;; esac
    [ "${a[1]##*/}" = frr_te_monitor.sh ] && n=$((n + 1))
done
echo "実行中の te_monitor: ${n} 個 (1個が正常)"

echo "── 重みファイル ───────────────────────────"
if [ -r "$WEIGHTS_FILE" ]; then
    ts=$(sed -n 's/^TS=//p' "$WEIGHTS_FILE")
    echo "$(grep -E '^(W1|W2|W3|CR1_BW_MBPS)=' "$WEIGHTS_FILE" | tr '\n' ' ')  更新から $(( $(date +%s) - ts )) 秒"
else
    echo "なし (制御は停止中)"
fi

echo "── LER_Ingress table 41 (AF41) ────────────"
docker exec LER_Ingress ip route show table 41 2>&1 \
    | grep -oE 'dev leri-cr[0-9]+( weight [0-9]+)?' \
    | awk '{printf "%s=%s  ", $2, ($4 == "" ? 1 : $4)}'   # weight 1 は ip が省略する
echo

echo "── te_monitor ログ (最新5行) ──────────────"
tail -n 5 "$LOG_FILE" 2>/dev/null || echo "ログなし: $LOG_FILE"
