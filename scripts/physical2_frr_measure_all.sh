#!/bin/bash
# physical2_frr_measure_all.sh
# PCで実行: 全シナリオを自動計測 (SW1/SW2をSSH経由で制御)
#
# 使い方:
#   bash scripts/physical2_frr_measure_all.sh [duration] [normal|failure|failure_reroute|all]
#
# 例:
#   bash scripts/physical2_frr_measure_all.sh 60 all          # 全3シナリオ
#   bash scripts/physical2_frr_measure_all.sh 60 normal       # normalのみ
#   bash scripts/physical2_frr_measure_all.sh 60 failure_reroute

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

SW1="kannolab@192.168.128.33"
SW2="kannolab@192.168.128.1"
KEY="$HOME/.ssh/lab_key"
SW1_SCRIPT="/home/kannolab/scripts/physical2_frr_measure_sw1.sh"
SW2_SCRIPT="/home/kannolab/scripts/physical2_frr_measure_sw2.sh"

DURATION=${1:-60}
TARGET=${2:-all}
EXP_TAG="${3:-$(date +%Y%m%d)}"

export LAB_MODE=physical
source "${SCRIPT_DIR}/lab_config.sh"
_to_mbps() {
    local r; r=$(echo "$1" | tr '[:upper:]' '[:lower:]')
    case "$r" in
        *g) echo "$(( ${r%g} * 1000 ))" ;;
        *m) echo "${r%m}" ;;
        *) echo "${r//[^0-9]/}" ;;
    esac
}
CR_MBPS=$(_to_mbps "${CR1_BW:-3G}")
TX_MBPS=$(_to_mbps "${TX1_RATE:-7G}")

SSH="ssh -i $KEY -o StrictHostKeyChecking=no -o BatchMode=yes"
SCP="scp -i $KEY -o StrictHostKeyChecking=no -o BatchMode=yes"

if ! [[ "$DURATION" =~ ^[0-9]+$ ]]; then
    echo "[ERROR] durationは数値で指定してください: '$DURATION'"
    exit 1
fi
if ! [[ "$TARGET" =~ ^(normal|failure|failure_reroute|all)$ ]]; then
    echo "[ERROR] シナリオは normal / failure / failure_reroute / all のいずれか"
    exit 1
fi

if [ "$TARGET" = "all" ]; then
    SCENARIOS=(normal failure failure_reroute)
else
    SCENARIOS=("$TARGET")
fi

EXP_DIR="${LAB_DIR}/results/frr/${EXP_TAG}"
mkdir -p "$EXP_DIR"

echo "████████████████████████████████████████"
echo "  OSPF-SR 物理2SW 自動計測"
echo "  シナリオ: ${SCENARIOS[*]}"
echo "  計測時間: ${DURATION}s/シナリオ"
echo "  実験タグ: ${EXP_TAG}  → ${EXP_DIR}"
echo "  CR帯域: ${CR1_BW}  TX: ${TX1_RATE}"
echo "████████████████████████████████████████"
echo ""

# スクリプトをSW1/SW2へデプロイ
echo "=== スクリプトデプロイ ==="
$SCP "${SCRIPT_DIR}/physical2_frr_measure_sw1.sh" "${SW1}:/home/kannolab/scripts/" \
    && echo "  [ok] sw1.sh → SW1" || echo "  [warn] sw1.sh デプロイ失敗"
$SCP "${SCRIPT_DIR}/physical2_frr_measure_sw2.sh" "${SW2}:/home/kannolab/scripts/" \
    && echo "  [ok] sw2.sh → SW2" || echo "  [warn] sw2.sh デプロイ失敗"
$SCP "${SCRIPT_DIR}/lab_config.sh"          "${SW1}:/home/kannolab/scripts/" \
    && echo "  [ok] lab_config.sh → SW1" || echo "  [warn] lab_config.sh デプロイ失敗"
$SCP "${SCRIPT_DIR}/lab_config_veth.sh"     "${SW1}:/home/kannolab/scripts/" \
    && echo "  [ok] lab_config_veth.sh → SW1" || echo "  [warn] lab_config_veth.sh デプロイ失敗"
$SCP "${SCRIPT_DIR}/lab_config_physical.sh" "${SW1}:/home/kannolab/scripts/" \
    && echo "  [ok] lab_config_physical.sh → SW1" || echo "  [warn] lab_config_physical.sh デプロイ失敗"
$SCP "${SCRIPT_DIR}/frr_dscp_te.sh" "${SW1}:/home/kannolab/scripts/" \
    && echo "  [ok] frr_dscp_te.sh → SW1" || echo "  [warn] frr_dscp_te.sh デプロイ失敗"
$SCP "${SCRIPT_DIR}/frr_te_monitor.sh" "${SW1}:/home/kannolab/scripts/" \
    && echo "  [ok] frr_te_monitor.sh → SW1" || echo "  [warn] frr_te_monitor.sh デプロイ失敗"
$SCP "${SCRIPT_DIR}/owd_receiver.py" "${SW2}:/home/kannolab/scripts/" \
    && echo "  [ok] owd_receiver.py → SW2" || echo "  [warn] owd_receiver.py デプロイ失敗"
$SCP "${SCRIPT_DIR}/owd_sender.py" "${SW1}:/home/kannolab/scripts/" \
    && echo "  [ok] owd_sender.py → SW1" || echo "  [warn] owd_sender.py デプロイ失敗"
echo ""

# SW1/SW2の時刻同期 (Python並列実行でオフセット最小化)
# 単純な「SW1読み→SW2設定」は2-3s遅延でOWDが歪む。
# 代わりにローカルPCの時刻を基準にSW1/SW2へ同時設定する。
echo "=== 時刻同期 (PC→SW1/SW2 並列) ==="
python3 - <<'PYSYNC'
import subprocess, threading, time

KEY = f"/home/kannolab/.ssh/lab_key"
SSH_OPTS = ["-i", KEY, "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
SW1 = "kannolab@192.168.128.33"
SW2 = "kannolab@192.168.128.1"

errors = []

def set_time(host, t_str, label):
    cmd = ["ssh"] + SSH_OPTS + [host, f"sudo date -u -s '{t_str}'"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        errors.append(f"[warn] {label} 時刻同期失敗: {r.stderr.strip()}")
    else:
        print(f"  [ok] {label} → {t_str} UTC")

# 同期基準: 1秒後のきりのよい時刻にジャスト合わせる
t0 = time.time()
t_sync = int(t0) + 2  # 2秒後
t_str = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(t_sync))

# 2秒後に同時発火
delay = t_sync - time.time()
if delay > 0:
    time.sleep(delay)

th1 = threading.Thread(target=set_time, args=(SW1, t_str, "SW1"))
th2 = threading.Thread(target=set_time, args=(SW2, t_str, "SW2"))
th1.start(); th2.start()
th1.join(); th2.join()

for e in errors:
    print(e)
PYSYNC
echo ""

# SW1でfrr_dscp_te.shを実行 (SP fix + AF43 TCP fix + cburst を毎回適用)
echo "=== TC/HTB QoS 適用 (SW1: frr_dscp_te.sh) ==="
$SSH "$SW1" "sudo LAB_MODE=physical bash /home/kannolab/scripts/frr_dscp_te.sh" \
    && echo "  [ok] TC/HTB/iptables 再設定完了" \
    || echo "  [warn] frr_dscp_te.sh 失敗 — 継続しますが設定が古い可能性あり"
echo ""

run_scenario() {
    local scenario=$1
    local results_dir="${EXP_DIR}/frr_${scenario}"
    mkdir -p "$results_dir"

    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  シナリオ開始: ${scenario}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # SW2でサーバー起動 (バックグラウンド)
    echo "  [SW2] サーバー起動..."
    $SSH "$SW2" "sudo bash $SW2_SCRIPT $DURATION $scenario" &
    SW2_PID=$!

    # SW2のサーバー起動完了を待つ (15秒)
    sleep 15

    # SW1でクライアント起動 (フォアグラウンド、完了まで待機)
    echo "  [SW1] 計測開始 (${DURATION}s)..."
    $SSH "$SW1" "sudo bash $SW1_SCRIPT $DURATION $scenario"

    # SW2の完了を待つ (タイムアウト: DURATION + 60s)
    echo "  [SW2] 完了待ち (最大 $(( DURATION + 60 ))s)..."
    _sw2_timeout=$(( DURATION + 60 ))
    for _i in $(seq 1 "$_sw2_timeout"); do
        kill -0 "$SW2_PID" 2>/dev/null || break
        sleep 1
    done
    kill "$SW2_PID" 2>/dev/null || true
    sleep 2
    kill -9 "$SW2_PID" 2>/dev/null || true
    wait "$SW2_PID" 2>/dev/null || true

    # 結果収集
    echo "  [PC] 結果収集中..."
    _scp() {
        local src=$1 dst=$2
        if $SCP "$src" "$dst"; then
            echo "    [ok] $(basename "$src")"
        else
            echo "    [warn] SCP失敗: $src"
        fi
    }
    _scp "${SW2}:/tmp/frr_results_${scenario}/throughput.csv"        "$results_dir/"
    _scp "${SW2}:/tmp/frr_results_${scenario}/owd_af41.log"          "$results_dir/"
    _scp "${SW2}:/tmp/frr_results_${scenario}/owd_af42.log"          "$results_dir/"
    _scp "${SW2}:/tmp/frr_results_${scenario}/owd_af43.log"          "$results_dir/"
    _scp "${SW1}:/tmp/frr_results_${scenario}/iperf3_af41.log"       "$results_dir/"
    _scp "${SW1}:/tmp/frr_results_${scenario}/iperf3_af42.log"       "$results_dir/"
    _scp "${SW1}:/tmp/frr_results_${scenario}/iperf3_af43.log"       "$results_dir/"
    _scp "${SW1}:/tmp/frr_results_${scenario}/path_stats.csv"        "$results_dir/"
    _scp "${SW1}:/tmp/frr_results_${scenario}/htb_class_stats.csv"   "$results_dir/"
    _scp "${SW1}:/tmp/frr_results_${scenario}/htb_class_stats_cr2.csv" "$results_dir/"

    echo ""
    echo "  [ok] ${scenario} 完了 → $results_dir"
    ls -lh "$results_dir/"*.csv "$results_dir/"*.log 2>/dev/null | sed 's/^/       /'
    echo ""

    # シナリオ間のインターバル (OSPF再収束待ち)
    if [ ${#SCENARIOS[@]} -gt 1 ]; then
        echo "  次のシナリオまで10秒待機 (OSPF安定化)..."
        sleep 10
    fi
}

for scenario in "${SCENARIOS[@]}"; do
    run_scenario "$scenario"
done

# グラフ生成
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  グラフ生成"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
SRC_PLOT="${LAB_DIR}/results/frr/plot_frr.py"
PLOT_SCRIPT="${EXP_DIR}/plot_frr.py"
if [ -f "$SRC_PLOT" ]; then
    cp "$SRC_PLOT" "$PLOT_SCRIPT"
    python3 "$PLOT_SCRIPT" --cr-mbps "$CR_MBPS" \
        && echo "  [ok] グラフ生成完了: ${EXP_DIR}/"
else
    echo "  [warn] plot_frr.py が見つかりません: $SRC_PLOT"
fi

echo ""
echo "████████████████████████████████████████"
echo "  全シナリオ完了"
echo "████████████████████████████████████████"
