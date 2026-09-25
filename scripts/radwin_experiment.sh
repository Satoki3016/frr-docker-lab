#!/bin/bash
# RADWIN / C2 実験の操作入口。既存スクリプトを同じ条件で呼び出す。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

usage() {
    cat <<'EOF'
RADWIN 実験 (C2: 無線1経路 + 有線2経路)

  bash scripts/radwin_experiment.sh config [wcmp|ecmp|primary]
  sudo bash scripts/radwin_experiment.sh check
  sudo bash scripts/radwin_experiment.sh telemetry
  sudo bash scripts/radwin_experiment.sh prepare [wcmp|ecmp|primary]
  sudo bash scripts/radwin_experiment.sh control [タグ] [間隔秒=2]
  sudo bash scripts/radwin_experiment.sh run [計測秒=120] [タグ] [間隔秒=2] [normal|failure_reroute|manual]
  sudo bash scripts/radwin_experiment.sh measure [計測秒=60] [normal|failure|failure_reroute|manual|all] [タグ] [wcmp|ecmp|primary]

  config    使用する設定を表示 (sudo不要)
  check     HTB・マルチパス・ハッシュの前提確認のみ (設定変更・SSHなし)
  telemetry 無線状態を1回取得 (必要なら既存の管理用IPを追加)
  prepare   起動済みラボにQoSと経路を設定 (既定wcmp、コンテナは再構築しない)
  control   動的制御のみ。終了はCtrl+C。別途流すトラフィックを観測する用途
  run       QoS設定 → 計測 + 動的制御 → ログ回収・グラフ生成
            normal (既定): 計測中にアンテナを操作する容量変動実験用
            failure_reroute: t=20-40s の CR1 障害と te_monitor の迂回に動的制御を重ねる
            manual: 自動の障害注入なし・te_monitor あり。障害は人が起こす (ケーブル抜去など)
            (failure は「迂回なし」の比較用なので動的制御とは組み合わせない)
  measure   動的制御を併用せず、既存の単一/3シナリオ計測を実行

  --plan を先頭に付けると実行内容のみ表示 (sudo不要・ファイル作成なし):
    bash scripts/radwin_experiment.sh --plan run 120 antenna

保存名の規則 (CLAUDE.md): YYYYMMDD_結果_目的_条件_連番
  結果は自動で付く: 実行中 running → 終了時に success / fail
  (running のまま残っていれば、途中で強制終了されたことを示す)
  省略         → 20260919_running_dynamic_wcmp_01 → 終了時 20260919_success_dynamic_wcmp_01
  目的語だけ   → antenna なら 20260919_running_antenna_wcmp_01 (推奨)
  完全形       → 20260919_antenna_wcmp_07 のように結果語なしで渡す (結果語は自動で付く)
  連番は results/frr 全体を見て採番する。既存の実験番号は上書きしない。

ログ: run/control → results/frr/radwin/dynamic/<タグ>/
      measure     → results/frr/radwin/comparison/<タグ>/
詳細: docs/radwin_experiment.md
従来の radwin_wcmp_controller.py --interval 2 もそのまま使用可能。
EOF
}
die() { echo "[ERROR] $*" >&2; exit 1; }

PLAN=0
if [ "${1:-}" = "--plan" ]; then PLAN=1; shift; fi
ACTION="${1:-help}"
[ "$#" -eq 0 ] || shift
case "$ACTION" in help|-h|--help) usage; exit 0 ;; esac

DURATION=120
INTERVAL=2
SCENARIO=normal
MODE=wcmp
TAG=""
case "$ACTION" in
    config|prepare)
        [ "$#" -le 1 ] || die "引数が多すぎます (help を参照)"
        MODE="${1:-wcmp}" ;;
    check|telemetry)
        [ "$#" -eq 0 ] || die "$ACTION は引数不要です" ;;
    control)
        [ "$#" -le 2 ] || die "control [タグ] [間隔秒]"
        TAG="${1:-}"; INTERVAL="${2:-2}" ;;
    run)
        [ "$#" -le 4 ] || die "run [計測秒] [タグ] [間隔秒] [normal|failure_reroute|manual]"
        DURATION="${1:-120}"; TAG="${2:-}"; INTERVAL="${3:-2}"; SCENARIO="${4:-normal}"
        [[ "$SCENARIO" =~ ^(normal|failure_reroute|manual)$ ]] \
            || die "run のシナリオは normal / failure_reroute / manual (failure は迂回なしの比較用で動的制御と組み合わせない)" ;;
    measure)
        [ "$#" -le 4 ] || die "measure [計測秒] [シナリオ] [タグ] [モード]"
        DURATION="${1:-60}"; SCENARIO="${2:-normal}"; TAG="${3:-}"; MODE="${4:-wcmp}" ;;
    *) die "不明な操作: $ACTION (help を参照)" ;;
esac
[[ "$MODE" =~ ^(wcmp|ecmp|primary)$ ]] || die "モードは wcmp / ecmp / primary"
[[ "$SCENARIO" =~ ^(normal|failure|failure_reroute|manual|all)$ ]] || die "シナリオ名を確認してください"
[[ "$DURATION" =~ ^[1-9][0-9]*$ ]] || die "計測秒数は正の整数"
[[ "$INTERVAL" =~ ^[0-9]+([.][0-9]+)?$ ]] && [[ "$INTERVAL" =~ [1-9] ]] || die "間隔は正の秒数"
if [[ "$SCENARIO" != normal ]] && (( DURATION < 45 )); then
    die "障害シナリオは40秒時点の復旧を含めるため45秒以上を指定してください"
fi

# ラッパーの設定だけをC2に固定する。既存 lab_config.sh の既定値は変えない。
set -a
LAB_MODE=c2
ROUTE_MODE="$MODE"
source "$SCRIPT_DIR/lab_config_c2.sh"
set +a
# 呼び出し元の環境に同時計測の内部変数があっても、静的計測には持ち込まない。
unset RADWIN_CONTROLLER_CSV RADWIN_CONTROLLER_INTERVAL

CONFIG_KEYS=(LAB_MODE ROUTE_MODE CR1_BW CR2_BW CR3_BW
    IPERF_STREAMS TX1_RATE TX2_RATE TX3_RATE IPERF_DGRAM
    WCMP_W1 WCMP_W2 WCMP_W3 INGRESS_POLICE WRR_HI WRR_ME WRR_LO
    PFIFO_LIMIT_HI PFIFO_LIMIT_ME PFIFO_LIMIT_LO CR1_DELAY CR2_DELAY CR3_DELAY)
show_config() {
    for key in "${CONFIG_KEYS[@]}"; do printf '%s=%q\n' "$key" "${!key}"; done
    printf 'PRIO_HI=%q\nIPERF_STAGGER=%q\n' "${PRIO_HI:-0}" "${IPERF_STAGGER:-0.7}"
    printf 'CONTROLLER_INTERVAL=%q\nDURATION=%q\nSCENARIO=%q\n' "$INTERVAL" "$DURATION" "$SCENARIO"
    printf 'FRR_RESULTS_ROOT=%q\n' "${FRR_RESULTS_ROOT:-}"
}
if [ "$ACTION" = config ]; then show_config; exit 0; fi

# 制御本体は有線9G・SP有効・WRR 4:2:1固定。異なる条件を混ぜて記録しない。
if [[ "$ACTION" = run || "$ACTION" = control ]]; then
    [[ "$CR2_BW" =~ ^(9[Gg]|9000[Mm])$ && "$CR3_BW" =~ ^(9[Gg]|9000[Mm])$ ]] || die "動的制御は有線9G固定です"
    [[ "$WRR_HI:$WRR_ME:$WRR_LO:${PRIO_HI:-0}" = "4:2:1:0" ]] || die "動的制御はSP有効・WRR 4:2:1固定です"
fi

# 命名規則 (CLAUDE.md / results/frr/README.md): YYYYMMDD_結果_目的_条件_連番
#   結果は running (実行中・中断) / success / fail。終了時にこのスクリプトが付け替える。
#   連番の採番と重複検査では結果語を無視する (結果が違っても同じ実験番号は使わない)。
#   旧形式 YYYYMMDD_目的_条件_連番 (結果語なし) のフォルダも同じ番号として数える。
_RESULT_WORDS="running|success|fail"
_strip_result() {   # "D_success_rest" → "D_rest"。結果語が無ければそのまま
    local name=$1
    if [[ "$name" =~ ^([0-9]{8})_(running|success|fail)_(.+)$ ]]; then
        echo "${BASH_REMATCH[1]}_${BASH_REMATCH[3]}"
    else
        echo "$name"
    fi
}
_with_result() {    # "D_rest" + 結果語 → "D_結果_rest"
    echo "${1:0:8}_${2}_${1:9}"
}
_next_seq() {       # 引数: 結果語を除いた接頭辞 YYYYMMDD_目的_条件
    local prefix=$1 n=0 d base s
    shopt -s globstar nullglob
    for d in "$LAB_DIR/results/frr"/**/"${prefix:0:8}"_*; do
        [ -d "$d" ] || continue
        base="$(_strip_result "$(basename "$d")")"
        [[ "$base" == "${prefix}_"* ]] || continue
        s="${base##*_}"
        [[ "$s" =~ ^[0-9]+$ ]] || continue
        (( 10#$s > n )) && n=$((10#$s))
    done
    shopt -u globstar nullglob
    printf '%02d' $((n + 1))
}

RUN_DIR=""
if [[ "$ACTION" = control || "$ACTION" = run || "$ACTION" = measure ]]; then
    case "$ACTION" in
        run)     _purpose=dynamic ;;
        control) _purpose=control ;;
        measure) _purpose=compare ;;
    esac
    if [ -z "$TAG" ]; then
        # 未指定: 操作とモードから規則どおりに組み立てる
        _prefix="$(date +%Y%m%d)_${_purpose}_${MODE}"
        TAG="${_prefix}_$(_next_seq "$_prefix")"
    elif [[ "$TAG" =~ ^[[:alnum:]][[:alnum:].-]*$ ]]; then
        # 目的語だけ渡された場合 (例: antenna) は日付・条件・連番を補完する
        _prefix="$(date +%Y%m%d)_${TAG}_${MODE}"
        TAG="${_prefix}_$(_next_seq "$_prefix")"
    else
        [[ "$TAG" =~ ^[[:alnum:]][[:alnum:]_.-]*$ ]] \
            || die "タグには英数字・日本語・_・-・. を使用 (先頭は文字/数字)"
        TAG="$(_strip_result "$TAG")"      # 結果語は終了時に付けるので、渡されても外す
        [[ "$TAG" =~ ^[0-9]{8}_.+_.+_[0-9]+$ ]] \
            || echo "[注意] タグが規則 YYYYMMDD_目的_条件_連番 と異なります: $TAG" >&2
    fi
    BASE_TAG="$TAG"
    [[ "$BASE_TAG" =~ ^[0-9]{8}_ ]] || die "タグは日付 YYYYMMDD で始めてください: $BASE_TAG"
    TAG="$(_with_result "$BASE_TAG" running)"
    echo "保存名: $TAG (終了時に running を success / fail に付け替えます)"
    if [ "$ACTION" = measure ]; then
        export FRR_RESULTS_ROOT="$LAB_DIR/results/frr/radwin/comparison"
    else
        export FRR_RESULTS_ROOT="$LAB_DIR/results/frr/radwin/dynamic"
    fi
    RUN_DIR="$FRR_RESULTS_ROOT/$TAG"
    [ ! -e "$RUN_DIR" ] || die "保存先が既にあります。別のタグを指定してください: $RUN_DIR"
    # 分類先や結果語が違っても同じ実験番号を再利用しない (検索を一意に保つ)。
    shopt -s globstar nullglob
    for existing in "$LAB_DIR/results/frr"/**/"${BASE_TAG:0:8}"_*; do
        [ -d "$existing" ] || continue
        [ "$(_strip_result "$(basename "$existing")")" != "$BASE_TAG" ] \
            || die "同じ実験番号が既にあります。別のタグを指定してください: $existing"
    done
    shopt -u globstar nullglob
fi

if [ "$PLAN" -eq 0 ]; then
    [ "$(id -u)" -eq 0 ] || die "sudo bash scripts/radwin_experiment.sh $ACTION ... として実行してください"
    # この入口からの制御・設定・計測の重複実行を防ぐ。状態確認は並行可能。
    if [[ "$ACTION" != check && "$ACTION" != telemetry ]]; then
        exec 9>/run/lock/radwin_experiment.lock
        flock -n 9 || die "別のRADWIN実験を実行中です"
    fi
fi

# 合否の判定。run / measure は終了コード (validation.txt が NG なら 1)。
# control は Ctrl+C (130) が通常の終わり方なので、制御ログで判定する。
_result_word() {
    local rc=$1
    if [ "$ACTION" = control ]; then
        [[ "$rc" = 0 || "$rc" = 130 ]] || { echo fail; return; }
        [ ! -e "$RUN_DIR/controller.failed" ] || { echo fail; return; }
        [ "$(wc -l 2>/dev/null < "$RUN_DIR/controller.csv" || echo 0)" -ge 2 ] || { echo fail; return; }
        ! grep -q "_FAIL" "$RUN_DIR/controller.csv" 2>/dev/null || { echo fail; return; }
        echo success
    else
        [ "$rc" = 0 ] && echo success || echo fail
    fi
}
finish() {
    local rc=$?
    trap - EXIT
    if [ -n "$RUN_DIR" ] && [ "$PLAN" -eq 0 ]; then
        local result final
        result="$(_result_word "$rc")"
        printf 'exit_code=%s\nresult=%s\nfinished_at=%s\n' "$rc" "$result" "$(date -Is)" > "$RUN_DIR/status.txt"
        if [[ "${SUDO_UID:-}" =~ ^[0-9]+$ && "${SUDO_GID:-}" =~ ^[0-9]+$ ]]; then
            chown -R "$SUDO_UID:$SUDO_GID" "$RUN_DIR" || echo "[WARN] 結果の所有者変更に失敗しました" >&2
        fi
        final="$(dirname "$RUN_DIR")/$(_with_result "$BASE_TAG" "$result")"
        if mv -T "$RUN_DIR" "$final" 2>/dev/null; then
            RUN_DIR="$final"
        else
            echo "[WARN] 結果名への付け替えに失敗しました (running のまま): $RUN_DIR" >&2
        fi
        echo "結果: $RUN_DIR (終了コード $rc / $result)"
    fi
    exit "$rc"
}
if [ -n "$RUN_DIR" ]; then
    echo "保存先: $RUN_DIR"
    if [ "$PLAN" -eq 0 ]; then
        mkdir -p "$(dirname "$RUN_DIR")"
        mkdir "$RUN_DIR"
        trap finish EXIT
        trap 'exit 130' INT
        trap 'exit 143' TERM
        show_config > "$RUN_DIR/settings.env"
        printf 'action=%s\nstarted_at=%s\n' "$ACTION" "$(date -Is)" > "$RUN_DIR/run.info"
        printf 'running\n' > "$RUN_DIR/status.txt"
        sha256sum "$SCRIPT_DIR"/{radwin_experiment.sh,radwin_wcmp_controller.py,radwin_telemetry.py,radwin_ssh.py,lab_config.sh,lab_config_c2.sh,frr_dscp_te.sh,frr_measure.sh,frr_te_monitor.sh,run_all_scenarios.sh} \
            "$LAB_DIR/results/frr/plot_frr.py" > "$RUN_DIR/source_sha256.txt"
    fi
fi

invoke() {
    printf '+ '; printf '%q ' "$@"; printf '\n'
    [ "$PLAN" -eq 0 ] || return 0
    if [ -n "$RUN_DIR" ]; then
        { printf '%q ' "$@"; printf '\n'; } >> "$RUN_DIR/commands.log"
        "$@" 2>&1 | tee -a "$RUN_DIR/console.log"
    else
        "$@"
    fi
}

echo "LAB_MODE=c2 / ROUTE_MODE=$ROUTE_MODE / CR=$CR1_BW,$CR2_BW,$CR3_BW"
echo "送信: 各クラス${IPERF_STREAMS}フロー / 1フローあたりAF41=$TX1_RATE AF42=$TX2_RATE AF43=$TX3_RATE"
case "$ACTION" in
    check) invoke python3 "$SCRIPT_DIR/radwin_wcmp_controller.py" --check ;;
    telemetry) invoke python3 "$SCRIPT_DIR/radwin_telemetry.py" ;;
    prepare) invoke bash "$SCRIPT_DIR/frr_dscp_te.sh" ;;
    control)
        invoke python3 -u "$SCRIPT_DIR/radwin_wcmp_controller.py" \
            --interval "$INTERVAL" --log-csv "$RUN_DIR/controller.csv" ;;
    run)
        invoke bash "$SCRIPT_DIR/frr_dscp_te.sh"
        invoke env RADWIN_CONTROLLER_CSV="$RUN_DIR/controller.csv" RADWIN_CONTROLLER_INTERVAL="$INTERVAL" \
            bash "$SCRIPT_DIR/frr_measure.sh" "$DURATION" "$SCENARIO" "$TAG" ;;
    measure)
        if [ "$SCENARIO" = all ]; then
            invoke bash "$SCRIPT_DIR/run_all_scenarios.sh" "$DURATION" "$TAG"
        else
            invoke bash "$SCRIPT_DIR/frr_dscp_te.sh"
            invoke bash "$SCRIPT_DIR/frr_measure.sh" "$DURATION" "$SCENARIO" "$TAG"
        fi ;;
esac

if [[ "$ACTION" = run || "$ACTION" = measure ]] && [ "$PLAN" -eq 0 ]; then
    # 既存計測はiperfの失敗でも終了コード0になり得るため、欠測を別途検査する。
    python3 - "$RUN_DIR" "$IPERF_STREAMS" "$SCENARIO" "$ACTION" "${PRIO_HI:-0}" <<'PY'
import csv
import re
import sys
from pathlib import Path
base, streams, scenario, action, prio = sys.argv[1:]
base = Path(base)
scenarios = ("normal", "failure", "failure_reroute") if scenario == "all" else (scenario,)
errors = []
lines = []
for scenario in scenarios:
    folder = base / ("frr_" + scenario + ("_priouniform" if prio == "1" else ""))
    for cls, port in ((41, 1000), (42, 2000), (43, 3000)):
        path = folder / f"iperf3_af{cls}.log"
        data = path.read_text(errors="replace") if path.exists() else ""
        count = len(re.findall(rf"connected to [0-9.]+ port {port}$", data, re.M))
        ok = count == int(streams) and "iperf3: error" not in data and "receiver" in data
        line = f"{scenario} AF{cls}: {count}/{streams} streams / {'OK' if ok else 'NG'}"
        lines.append(line)
        if not ok:
            errors.append(line)
if action == "run":
    path = base / "controller.csv"
    rows = list(csv.DictReader(path.open())) if path.exists() else []
    failures = sum("FAIL" in row.get("action", "") for row in rows)
    active = sum(row.get("action") in ("init", "down", "up", "keep") for row in rows)
    ok = bool(active) and not failures and not (base / "controller.failed").exists()
    line = f"controller: {len(rows)} samples / {failures} apply failures / {'OK' if ok else 'NG'}"
    lines.append(line)
    if not ok:
        errors.append(line)
text = "\n".join(lines) + "\n"
(base / "validation.txt").write_text(text)
print(text, end="")
if errors:
    print("[NG] 欠測または制御失敗があります。ログを確認してください。", file=sys.stderr)
    sys.exit(1)
PY
fi
