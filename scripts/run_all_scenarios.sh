#!/bin/bash
# 3シナリオ (normal / failure / failure_reroute) を順番に実行し、
# 終了後に比較グラフを生成する。
#
# 使い方:
#   sudo env LAB_MODE=<mode> bash scripts/run_all_scenarios.sh [duration] [tag]
#   sudo env LAB_MODE=c2 bash scripts/run_all_scenarios.sh 60 20260911_success_radwin_cr1
#   sudo env LAB_MODE=c2 bash scripts/run_all_scenarios.sh 30 test   # 短縮テスト
#
# ★LAB_MODE を必ず指定すること。未指定だと veth 既定になり CR_BW が全経路 9G になる。
#   CR1 を無線化している構成 (LAB_MODE=c2) では CR1_BW=900M でなければ、
#   HTB がボトルネックにならず無線側で無秩序に落ちて QoS 実証が成立しない。

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

DURATION="${1:-60}"
TAG="${2:-$(date +%Y%m%d)_experiment}"

# 実効設定を表示する。LAB_MODE の指定漏れによる帯域取り違えを目視で防ぐため。
source "${SCRIPT_DIR}/lab_config.sh"

echo "════════════════════════════════════════"
echo "  FRR OSPF-SR 3シナリオ一括実行"
echo "  各 ${DURATION}s × 3 シナリオ"
echo "  タグ: ${TAG}"
echo "  LAB_MODE: ${LAB_MODE:-veth (未指定)}"
echo "  CR_BW   : CR1=${CR1_BW} / CR2=${CR2_BW} / CR3=${CR3_BW}"
echo "  TX_RATE : ${TX1_RATE} / ${TX2_RATE} / ${TX3_RATE} (各 ${IPERF_STREAMS:-4} ストリーム)"
echo "  UDPデータグラム長: ${IPERF_DGRAM:-8950} B (全長 $(( ${IPERF_DGRAM:-8950} + 32 )) B)"
case "${ROUTE_MODE:-primary}" in
  ecmp) echo "  経路分配: ecmp — 3経路 等重み 1:1:1 (容量を見ない。ベースライン)" ;;
  wcmp) echo "  経路分配: wcmp — 3経路 重み ${WCMP_W1:-1}:${WCMP_W2:-10}:${WCMP_W3:-10} (容量比)" ;;
  *)    echo "  経路分配: primary — CR1 主経路 + CR2/CR3 フォールバック (従来)" ;;
esac
echo "════════════════════════════════════════"

if [ "${LAB_MODE:-}" != "c2" ] && [ "${CR1_BW}" = "${CR2_BW}" ]; then
    echo ""
    echo "  [警告] CR1_BW と CR2_BW が同じ値です。"
    echo "         CR1 を無線化した構成なら LAB_MODE=c2 の指定漏れの可能性があります。"
    echo "         意図した設定か確認してください (5秒後に続行)"
    sleep 5
fi

# ストリーム確立数を検査する。iperf3 は1本でも確立に失敗すると計測全体を
# 中断するため、クラスが丸ごと欠測しても気づきにくい (2026-09-17 に遭遇)。
# --get-server-output によりサーバ側の "connected to" 行も混ざるので、
# 宛先ポートがクラス固定ポート (1000/2000/3000) の行 = クライアント側だけを数える。
_check_streams() {
    local rd="$1" want="$2" bad=0 c port log got
    for c in 41 42 43; do
        case "$c" in 41) port=1000 ;; 42) port=2000 ;; 43) port=3000 ;; esac
        log="${rd}/iperf3_af${c}.log"
        [ -f "$log" ] || { echo "  [NG] AF${c}: ログが無い"; bad=1; continue; }
        got=$(grep -cE "connected to [0-9.]+ port ${port}\$" "$log" 2>/dev/null || echo 0)
        if [ "$got" -ne "$want" ]; then
            echo "  [NG] AF${c}: ${got}/${want} 本しか確立できていない"
            grep -m1 -E 'iperf3: error' "$log" 2>/dev/null | sed 's/^/        /'
            bad=1
        fi
    done
    return $bad
}

MAX_TRY="${MAX_TRY:-3}"

for SCENARIO in normal failure failure_reroute; do
    echo ""
    echo "════════════════════════════════════════"
    echo "  シナリオ: ${SCENARIO}"
    echo "════════════════════════════════════════"

    _rd="${FRR_RESULTS_ROOT:-${LAB_DIR}/results/frr/incoming}/${TAG}/frr_${SCENARIO}"
    _want="${IPERF_STREAMS:-4}"
    _ok=0
    for _try in $(seq 1 "$MAX_TRY"); do
        [ "$_try" -gt 1 ] && echo "  --- 再試行 ${_try}/${MAX_TRY} (ストリーム取りこぼしのため) ---"
        # ここで sudo を使わないこと。本スクリプトは既に root で動いており、
        # sudo は env_reset で LAB_MODE を捨てるため lab_config が veth 既定に落ち、
        # CR_BW が意図しない値になる (2026-09-11 に発見)。
        bash "${SCRIPT_DIR}/frr_dscp_te.sh"
        bash "${SCRIPT_DIR}/frr_measure.sh" "$DURATION" "$SCENARIO" "$TAG"

        if _check_streams "$_rd" "$_want"; then
            echo "  [ok] 3クラスとも ${_want} 本すべて確立"
            _ok=1
            break
        fi
        # 取りこぼしは一斉接続でサーバ側の accept キューが溢れるために起きる。
        # 短い間隔で再試行すると TIME_WAIT のソケットが積み上がって悪化するため、
        # 既定の TIME_WAIT (60秒) が掃けるまで待ってから再試行する。
        # 2026-09-18: sleep 10 では3回とも失敗した。
        if [ "$_try" -lt "$MAX_TRY" ]; then
            echo "  TIME_WAIT が掃けるまで65秒待機..."
            sleep 65
        fi
    done

    if [ "$_ok" = "0" ]; then
        echo "  [警告] ${MAX_TRY}回とも欠測。このシナリオのデータは使えない。"
        echo "         IPERF_STREAMS を下げて (例: 32) 実行し直すこと。"
    fi

    echo "  [完了] ${SCENARIO}"
    # 次のシナリオ前に OSPF が完全に安定するまで待機
    sleep 5
done

echo ""
echo "════════════════════════════════════════"
echo "  全3シナリオ完了 — 比較グラフ生成"
echo "════════════════════════════════════════"

PLOT_SCRIPT="${LAB_DIR}/results/frr/plot_frr.py"
FRR_BASE="${FRR_RESULTS_ROOT:-${LAB_DIR}/results/frr/incoming}/${TAG}"

if [ -n "$SUDO_USER" ]; then
    sudo -u "$SUDO_USER" python3 "$PLOT_SCRIPT" --base "$FRR_BASE"
else
    python3 "$PLOT_SCRIPT" --base "$FRR_BASE"
fi

echo ""
echo "グラフ出力先: ${FRR_BASE}/figures/"
echo "════════════════════════════════════════"
