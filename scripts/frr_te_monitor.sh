#!/bin/bash
# OSPF-SR 動的TE経路モニター
#
# 役割:
#   leri-cr1/cr2/cr3 の障害/復旧を検知し、
#   ポリシールーティングテーブル (41/42/43) の SR-MPLS 明示経路を更新する。
#
# 検知方式 (二重化):
#   1. netlink (ip monitor link): operstate DOWN/UP イベント
#      → ip link set down のような直接的なリンクダウンを即座に検知
#   2. OSPF 隣接ポーリング (約2秒周期): show ip ospf neighbor で Full 状態を確認
#      → tc netem / iptables など operstate が変化しない障害を検知
#      → frr_measure.sh で OSPF タイマー短縮 (hello=1s/dead=3s) 時は ~5s で収束検知
#
# 改良点:
#   1. SIDラベルを OSPF 問い合わせで動的取得
#   2. リンク障害後に OSPF 収束 (隣接消滅/確立) を待ってからテーブルを再計算
#   3. 定期的 (30秒ごと) にラベルを再確認し、変化があればテーブルを更新
#
# 使い方:
#   sudo bash scripts/frr_te_monitor.sh [ログファイル]
#   sudo bash scripts/frr_te_monitor.sh &   # バックグラウンド実行

set -e
LOG_FILE="${1:-/tmp/frr_te_monitor.log}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lab_config.sh"

CR_DEVS=(leri-cr1 leri-cr2 leri-cr3)
CR_NAMES=(CR1 CR2 CR3)
SRGB_BASE=16000
OSPF_DOWN_WAIT=6    # 障害時 OSPF 隣接消滅待ち最大秒数
OSPF_UP_WAIT=15     # 復旧時 OSPF Full 確立待ち最大秒数

# CR の OSPF Router-ID (loopback アドレスと一致)
CR_ROUTER_IDS=("192.168.0.2" "192.168.0.3" "192.168.0.4")

log() { echo "[$(date '+%H:%M:%S')] $*" >> "$LOG_FILE"; }

# ── SIDラベル動的取得 ────────────────────────────────────────────────────
# 以下の優先順で LER_Egress の Node SID を取得する:
#   1. vtysh show ip ospf segment-routing  (FRR 8.4+ で利用可能)
#   2. カーネルルートの encap mpls エントリ (FRR が OSPF-SR で自動設定)
#   3. vtysh show ip route のラベルアノテーション
#   4. SRGB_BASE + 静的インデックス (フォールバック)
refresh_labels() {
    local new_lere=""

    # Method 1: カーネルルートの encap mpls エントリ (FRR が OSPF-SR で自動設定)
    # show ip ospf segment-routing は FRR 8.4_git ビルドに存在しないため使用しない
    new_lere=$(docker exec frr-LER_Ingress \
        ip route show 192.168.0.5/32 2>/dev/null \
        | grep -oP '(?<=encap mpls )[0-9]+' | head -1 || true)

    # Method 3: vtysh show ip route のラベルアノテーション
    if [ -z "$new_lere" ]; then
        new_lere=$(docker exec frr-LER_Ingress vtysh \
            -c "show ip route 192.168.0.5/32" 2>/dev/null \
            | grep -oP '(?i)\blabel[= ]\K[0-9]+' | head -1 || true)
    fi

    # Fallback: SRGB_BASE + 静的インデックス (frr_setup.sh の設定値と対応)
    if [ -z "$new_lere" ]; then
        new_lere=$(( SRGB_BASE + 5 ))
        log "  [SID] OSPF問い合わせ失敗 → フォールバック: LER_Egress=${new_lere}"
    else
        log "  [SID] OSPF動的取得: LER_Egress=${new_lere}"
    fi

    LERE_LABEL=$new_lere
    # CR SID はログ表示用のみ (ルーティングには単一ラベル方式で使用しない)
    CR1_LABEL=$(( SRGB_BASE + 2 ))
    CR2_LABEL=$(( SRGB_BASE + 3 ))
    CR3_LABEL=$(( SRGB_BASE + 4 ))
}

# ── OSPF neighbor 状態確認 ───────────────────────────────────────────────
ospf_neighbor_full() {
    # router_id が Full/* 状態にあれば 0 (true) を返す
    local router_id=$1
    docker exec frr-LER_Ingress vtysh \
        -c "show ip ospf neighbor" 2>/dev/null \
        | grep -q "^${router_id}.*Full/" || return 1
}

# OSPF 収束を待つ
# router_id : 対象 CR の Router-ID
# expected_up: 1 = Full 確立まで待つ / 0 = 隣接消滅まで待つ
wait_ospf_converge() {
    local router_id=$1 expected_up=$2
    local wait_sec; wait_sec=$([ "$expected_up" -eq 1 ] && echo "$OSPF_UP_WAIT" || echo "$OSPF_DOWN_WAIT")
    local state_str; state_str=$([ "$expected_up" -eq 1 ] && echo "Full確立" || echo "隣接消滅")
    local deadline=$(( $(date +%s) + wait_sec ))

    log "  [OSPF] ${router_id} ${state_str}を待機中 (最大${wait_sec}s)..."
    while [ "$(date +%s)" -lt "$deadline" ]; do
        local currently_full=0
        ospf_neighbor_full "$router_id" && currently_full=1 || currently_full=0

        if [ "$expected_up" -eq 1 ] && [ "$currently_full" -eq 1 ]; then
            log "  [OSPF] ${router_id} Full確立を確認"
            return 0
        fi
        if [ "$expected_up" -eq 0 ] && [ "$currently_full" -eq 0 ]; then
            log "  [OSPF] ${router_id} 隣接消滅を確認"
            return 0
        fi
        sleep 0.5
    done

    log "  [OSPF] ${router_id} 収束タイムアウト (${wait_sec}s) → 強制テーブル更新"
    return 0  # タイムアウト時もテーブル更新を続行
}

# ── ポリシールーティングテーブル更新 ────────────────────────────────────
# 1リンク3クラス設計: 全クラスが同一の優先順位 CR1→CR2→CR3 で動作
# state[0]=CR1, state[1]=CR2, state[2]=CR3  (0=up, 1=down)
state=(0 0 0)

# 最良の生存 CR を選ぶヘルパー
# 出力: "via_ip dev_name" または空文字 (全CR down)
_best_cr_via() {
    local idx=$1  # 0=CR1優先, 1=CR2優先, 2=CR3優先 (現在は常に0=CR1優先)
    local vias=("10.0.1.2 leri-cr1" "10.0.3.2 leri-cr2" "10.0.5.2 leri-cr3")
    local i
    for i in 0 1 2; do
        [ "${state[$i]}" -eq 0 ] && { echo "${vias[$i]}"; return; }
    done
    echo ""
}

update_tables() {
    refresh_labels

    # 主経路 (metric 1): 最初に生存しているCR
    # 副経路 (metric 2): 2番目に生存しているCR (全テーブルに追加)
    # 第3経路 (metric 3): 3番目に生存しているCR (table43のみ)
    # 生存CR無し: unreachable を設定して mainテーブルへのフォールスルーを防止

    local cr_names=("CR1" "CR2" "CR3")
    local cr_vias=("10.0.1.2 leri-cr1" "10.0.3.2 leri-cr2" "10.0.5.2 leri-cr3")
    local primary="" secondary="" tertiary="" active_name=""

    for i in 0 1 2; do
        if [ "${state[$i]}" -eq 0 ]; then
            if [ -z "$primary" ]; then
                primary="${cr_vias[$i]}"
                active_name="${cr_names[$i]}"
            elif [ -z "$secondary" ]; then
                secondary="${cr_vias[$i]}"
            elif [ -z "$tertiary" ]; then
                tertiary="${cr_vias[$i]}"
            fi
        fi
    done

    local pri_via="" pri_dev=""
    if [ -n "$primary" ]; then
        pri_via="${primary% *}"; pri_dev="${primary#* }"
    fi
    local sec_via="" sec_dev=""
    if [ -n "$secondary" ]; then
        sec_via="${secondary% *}"; sec_dev="${secondary#* }"
    fi

    # ip route replace を使い「テーブル空白期間ゼロ」でルートを更新する
    # 主経路のみ管理: 副経路は事前に設定せず、障害検知時に主経路を切り替える
    # (frr_failure との比較のため、preemptive fallback を持たせない設計)
    local lbl="${LERE_LABEL}"
    if [ -n "$pri_via" ]; then
        # 主経路を atomic に更新 (replace = 既存あれば置換 / なければ add と等価)
        docker exec LER_Ingress bash -c "
            for tbl in 41 42 43; do
                ip route replace table \$tbl 10.20.0.0/16 encap mpls ${lbl} \
                    via ${pri_via} dev ${pri_dev} metric 1 2>/dev/null || \
                ip route add    table \$tbl 10.20.0.0/16 encap mpls ${lbl} \
                    via ${pri_via} dev ${pri_dev} metric 1 2>/dev/null || true
                ip route del table \$tbl 10.20.0.0/16 metric 2 2>/dev/null || true
                ip route del table \$tbl 10.20.0.0/16 metric 3 2>/dev/null || true
            done
        " 2>/dev/null || true
    else
        # 全CR down → unreachable (mainテーブルへのフォールスルー防止)
        docker exec LER_Ingress bash -c "
            for tbl in 41 42 43; do
                ip route flush table \$tbl 2>/dev/null || true
                ip route add table \$tbl unreachable 10.20.0.0/16 metric 1 2>/dev/null || true
            done
        " 2>/dev/null || true
    fi

    local up_list=""
    [ "${state[0]}" -eq 0 ] && up_list="${up_list} CR1"
    [ "${state[1]}" -eq 0 ] && up_list="${up_list} CR2"
    [ "${state[2]}" -eq 0 ] && up_list="${up_list} CR3"
    log "  TE更新: SID=${LERE_LABEL} / 主経路=${active_name:-NONE} / 有効CR:${up_list}"
    log "  table41/42/43 全クラス → ${active_name:-unreachable}"
}

# ── OSPF 隣接ポーリング ───────────────────────────────────────────────────
# netlink が発火しない障害 (netem/iptables) を ~2秒周期で補完検知する
_ospf_poll_last=0
check_ospf_neighbors() {
    local now; now=$(date +%s)
    # 1秒未満の連呼を抑制
    (( now - _ospf_poll_last < 1 )) && return
    _ospf_poll_last=$now

    for i in 0 1 2; do
        local currently_full=0
        ospf_neighbor_full "${CR_ROUTER_IDS[$i]}" && currently_full=1 || currently_full=0

        if [ "${state[$i]}" -eq 0 ] && [ "$currently_full" -eq 0 ]; then
            # 正常 → 隣接消失: netem/iptables 障害を検知
            log "⚠  ${CR_NAMES[$i]} OSPF隣接消失検知 (ポーリング) → テーブル更新"
            state[$i]=1
            update_tables
        elif [ "${state[$i]}" -eq 1 ] && [ "$currently_full" -eq 1 ]; then
            # 障害 → Full回復: netem 解除後の自然復旧を検知
            log "✓  ${CR_NAMES[$i]} OSPF Full回復検知 (ポーリング) → テーブル更新"
            state[$i]=0
            update_tables
        fi
    done
}

# ── リンク状態取得 ───────────────────────────────────────────────────────
get_operstate() {
    docker exec LER_Ingress cat "/sys/class/net/$1/operstate" 2>/dev/null || echo "unknown"
}
is_down() { [ "$1" = "down" ]; }

# ── 起動時の初期化 ───────────────────────────────────────────────────────
log "=== OSPF-SR TE Monitor 起動 (netlink イベント駆動 / OSPF収束ベース動的ラベル版) ==="
log "  検知方式: ip monitor link (netlink) / OSPF障害待ち: ${OSPF_DOWN_WAIT}s / OSPF復旧待ち: ${OSPF_UP_WAIT}s"
log "  ログ: $LOG_FILE"

for i in 0 1 2; do
    devs=(leri-cr1 leri-cr2 leri-cr3)
    os=$(get_operstate "${devs[$i]}")
    if is_down "$os"; then
        state[$i]=1
        log "  [起動時] ${devs[$i]}: DOWN"
    else
        state[$i]=0
    fi
done

update_tables
log "初期TE経路設定完了"

# ── netlink イベント駆動監視ループ ───────────────────────────────────────
# ip monitor link の出力を受け取るための名前付きパイプ
MONITOR_FIFO=$(mktemp -u /tmp/te_mon_XXXXXX)
mkfifo "$MONITOR_FIFO"

# FIFO を O_RDWR で開く → writer が終了しても EOF にならない
exec 3<>"$MONITOR_FIFO"

_cleanup() { rm -f "$MONITOR_FIFO"; kill "$MONITOR_PID" 2>/dev/null || true; }
trap _cleanup EXIT INT TERM

_start_monitor() {
    # docker exec はブロックバッファされるため nsenter で直接 NS に入る
    local pid; pid=$(docker inspect -f '{{.State.Pid}}' LER_Ingress)
    nsenter -t "$pid" -n -- ip monitor link 2>/dev/null > "$MONITOR_FIFO" &
    MONITOR_PID=$!
    log "  [netlink] nsenter ip monitor link 起動 PID=$MONITOR_PID (NS pid=${pid})"
}
_start_monitor

log "=== 監視ループ開始 (netlink + OSPF ポーリング 二重化) ==="
label_refresh_last=$(date +%s)
set +e   # デーモンループ: docker exec の一時的失敗でスクリプトを終了させない

while true; do
    # read -t 2: イベントがあれば即座 (<10ms) に返る、なければ2秒でタイムアウト
    # タイムアウトを短くすることで OSPF ポーリングの応答性を確保する
    if IFS= read -r -t 2 line <&3 2>/dev/null; then
        # インタフェース状態変化行を処理 (例: "3: leri-cr1: <...> state DOWN ...")
        # 数字から始まる行のみ対象 (link/ether 等の属性行は無視)
        [[ "$line" =~ ^[0-9]+:[[:space:]]([^:]+):[[:space:]].*state[[:space:]](UP|DOWN) ]] || true
        if [[ "$line" =~ ^[0-9]+:[[:space:]]([^:]+):[[:space:]].*state[[:space:]](UP|DOWN) ]]; then
            ifname="${BASH_REMATCH[1]%%@*}"   # "leri-cr1@if582" → "leri-cr1"
            newstate="${BASH_REMATCH[2]}"

            for i in 0 1 2; do
                [ "${CR_DEVS[$i]}" = "$ifname" ] || continue
                new_s=$([ "$newstate" = "DOWN" ] && echo 1 || echo 0)
                if [ "${state[$i]}" -eq "$new_s" ]; then break; fi  # 変化なし・スキップ

                if [ "$new_s" -eq 1 ]; then
                    log "⚠  ${CR_NAMES[$i]}(${ifname}) DOWN検知 (netlink) → OSPF収束待ち"
                    wait_ospf_converge "${CR_ROUTER_IDS[$i]}" 0
                    state[$i]=1
                else
                    log "✓  ${CR_NAMES[$i]}(${ifname}) UP復旧 (netlink) → OSPF収束待ち"
                    wait_ospf_converge "${CR_ROUTER_IDS[$i]}" 1
                    state[$i]=0
                fi
                update_tables
                break
            done
        fi
    fi

    # OSPF 隣接ポーリング: netem/iptables 障害 (operstate 変化なし) を補完検知
    check_ospf_neighbors

    # ip monitor プロセスが終了していたら再起動
    if ! kill -0 "$MONITOR_PID" 2>/dev/null; then
        log "⚡ ip monitor link プロセス終了 → 再起動"
        _start_monitor
    fi

    # 定期ラベル再確認 (30秒ごと): OSPF再収束でSIDが変わった場合に対応
    now=$(date +%s)
    if (( now - label_refresh_last >= 30 )); then
        old_label=${LERE_LABEL:-}
        refresh_labels
        if [ "${LERE_LABEL}" != "$old_label" ] && [ -n "$old_label" ]; then
            log "⚡ SID変更検知: ${old_label} → ${LERE_LABEL} → TE再設定"
            update_tables
        fi
        label_refresh_last=$now
    fi
done
