#!/bin/bash
# set_rates.sh — 送信レート対話式設定メニュー
#
# 使い方:
#   bash scripts/set_rates.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VETH_CFG="$SCRIPT_DIR/lab_config_veth.sh"
PHYSICAL_CFG="$SCRIPT_DIR/lab_config_physical.sh"

# ANSI カラー
C_VETH='\033[0;36m'       # シアン: veth
C_PHY='\033[0;33m'        # 黄: 物理
C_OK='\033[0;32m'         # 緑: 成功
C_WARN='\033[0;31m'       # 赤: 警告
C_BOLD='\033[1m'
C_RESET='\033[0m'

# ── ユーティリティ ─────────────────────────────────────────────────────

# 設定ファイルからデフォルト値を読む: TX1_RATE="${TX1_RATE:-3G}" → 3G
_get() {
    local file=$1 key=$2
    grep "^${key}=" "$file" 2>/dev/null \
        | sed 's/.*:-\([^}]*\)}.*/\1/' | head -1
}

# 設定ファイルのデフォルト値を書き換える
_set() {
    local file=$1 key=$2 val=$3
    sed -i "s|^${key}=\"\${${key}:-[^}]*}\"|${key}=\"\${${key}:-${val}}\"|" "$file"
}

# レート文字列を Mbps に変換 (表示・計算用)
_to_mbps() {
    local r; r=$(echo "$1" | tr '[:upper:]' '[:lower:]')
    case "$r" in
        *g) echo $(( ${r//[^0-9]/} * 1000 )) ;;
        *m) echo "${r//[^0-9]/}" ;;
        *k) echo "0" ;;
        *)  echo "${r//[^0-9]/}" ;;
    esac
}

# 入力値の形式チェック: 25G / 30M / 5M / 100 など
_valid() {
    [[ "$1" =~ ^[0-9]+(\.[0-9]+)?[GgMmKk]?$ ]]
}

# SP 割当に対して TX×4 が超過しているか判定して表示
_sp_hint() {
    local tx=$1 cr=$2 wrr_num=$3 wrr_den=$4
    local tx_mbps cr_mbps quota_mbps total_tx
    tx_mbps=$(_to_mbps "$tx")
    cr_mbps=$(_to_mbps "$cr")
    quota_mbps=$(( cr_mbps * wrr_num / wrr_den ))
    total_tx=$(( tx_mbps * 4 ))
    if [ "$total_tx" -le "$quota_mbps" ]; then
        echo -e "    ${C_OK}4×${tx} = ${total_tx}M ≤ 割当 ${quota_mbps}M → SP保護で無損失${C_RESET}"
    else
        echo -e "    ${C_WARN}4×${tx} = ${total_tx}M > 割当 ${quota_mbps}M → 損失発生${C_RESET}"
    fi
}

# ── 設定表示 ──────────────────────────────────────────────────────────

_show() {
    local file=$1 mode=$2
    local t1 t2 t3 cr color
    t1=$(_get "$file" TX1_RATE)
    t2=$(_get "$file" TX2_RATE)
    t3=$(_get "$file" TX3_RATE)
    cr=$(_get "$file" CR1_BW)
    [ "$mode" = "veth" ] && color="$C_VETH" || color="$C_PHY"

    local cr_mbps
    cr_mbps=$(_to_mbps "$cr")

    echo -e "  ${color}CR 帯域 : ${C_BOLD}${cr}${C_RESET}"
    echo ""
    echo -e "  ${C_BOLD}AF41（高優先 / SP）${C_RESET}  TX1_RATE = ${C_BOLD}${t1}${C_RESET}"
    _sp_hint "$t1" "$cr" 4 7
    echo ""
    echo -e "  ${C_BOLD}AF42（中優先 / WRR 2）${C_RESET}  TX2_RATE = ${C_BOLD}${t2}${C_RESET}"
    _sp_hint "$t2" "$cr" 2 7
    echo ""
    echo -e "  ${C_BOLD}AF43（低優先 / WRR 1）${C_RESET}  TX3_RATE = ${C_BOLD}${t3}${C_RESET}"
    _sp_hint "$t3" "$cr" 1 7
}

# ── 編集サブメニュー ──────────────────────────────────────────────────

_edit() {
    local mode=$1
    local file label color
    if [ "$mode" = "veth" ]; then
        file="$VETH_CFG"; label="veth（仮想環境）"; color="$C_VETH"
    else
        file="$PHYSICAL_CFG"; label="物理環境（2SW）"; color="$C_PHY"
    fi

    echo ""
    echo -e "${color}${C_BOLD}══════════════════════════════════════════${C_RESET}"
    echo -e "${color}${C_BOLD}  ${label}  —  送信レート設定${C_RESET}"
    echo -e "${color}${C_BOLD}══════════════════════════════════════════${C_RESET}"
    echo ""
    echo "  【現在の設定】"
    _show "$file" "$mode"
    echo ""
    echo -e "  新しい値を入力してください（Enter でスキップ）"
    echo -e "  書式例: ${C_BOLD}3G  15G  30M  5M${C_RESET}"
    echo ""

    local t1 t2 t3 cr new
    t1=$(_get "$file" TX1_RATE)
    t2=$(_get "$file" TX2_RATE)
    t3=$(_get "$file" TX3_RATE)
    cr=$(_get "$file" CR1_BW)

    # 各フィールドを入力（無効値は再入力を促す）
    _prompt() {
        local label=$1 cur=$2 out_var=$3
        local val
        while true; do
            read -rp "  ${label} [${cur}] > " val
            if [ -z "$val" ]; then
                eval "${out_var}=${cur}"; return
            elif _valid "$val"; then
                eval "${out_var}=${val}"; return
            else
                echo -e "  ${C_WARN}[!] 無効な値です（例: 3G / 30M）${C_RESET}"
            fi
        done
    }

    local new_t1 new_t2 new_t3 new_cr
    _prompt "AF41（高優先）TX1_RATE" "$t1" new_t1
    _prompt "AF42（中優先）TX2_RATE" "$t2" new_t2
    _prompt "AF43（低優先）TX3_RATE" "$t3" new_t3
    _prompt "CR 帯域       CR_BW   " "$cr" new_cr

    echo ""
    echo "  【変更後のプレビュー】"
    # 一時的に上書きして表示
    local tmp; tmp=$(mktemp)
    cp "$file" "$tmp"
    _set "$tmp" TX1_RATE "$new_t1"
    _set "$tmp" TX2_RATE "$new_t2"
    _set "$tmp" TX3_RATE "$new_t3"
    _set "$tmp" CR1_BW   "$new_cr"
    _set "$tmp" CR2_BW   "$new_cr"
    _set "$tmp" CR3_BW   "$new_cr"
    _show "$tmp" "$mode"
    rm -f "$tmp"

    echo ""
    read -rp "  保存しますか？ [y/N] > " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        _set "$file" TX1_RATE "$new_t1"
        _set "$file" TX2_RATE "$new_t2"
        _set "$file" TX3_RATE "$new_t3"
        _set "$file" CR1_BW   "$new_cr"
        _set "$file" CR2_BW   "$new_cr"
        _set "$file" CR3_BW   "$new_cr"
        echo -e "  ${C_OK}[ok] 保存しました → $(basename "$file")${C_RESET}"
    else
        echo "  キャンセルしました"
    fi
}

# ── メインメニュー ────────────────────────────────────────────────────

while true; do
    local_t1v=$(_get "$VETH_CFG"     TX1_RATE)
    local_t2v=$(_get "$VETH_CFG"     TX2_RATE)
    local_t3v=$(_get "$VETH_CFG"     TX3_RATE)
    local_crv=$(_get "$VETH_CFG"     CR1_BW)
    local_t1p=$(_get "$PHYSICAL_CFG" TX1_RATE)
    local_t2p=$(_get "$PHYSICAL_CFG" TX2_RATE)
    local_t3p=$(_get "$PHYSICAL_CFG" TX3_RATE)
    local_crp=$(_get "$PHYSICAL_CFG" CR1_BW)

    echo ""
    echo -e "${C_BOLD}══════════════════════════════════════════${C_RESET}"
    echo -e "${C_BOLD}  送信レート設定メニュー${C_RESET}"
    echo -e "${C_BOLD}══════════════════════════════════════════${C_RESET}"
    echo ""
    echo -e "  ${C_VETH}${C_BOLD}[1] veth（仮想環境）${C_RESET}"
    echo -e "  ${C_VETH}      TX1=${local_t1v}  TX2=${local_t2v}  TX3=${local_t3v}  CR=${local_crv}${C_RESET}"
    echo ""
    echo -e "  ${C_PHY}${C_BOLD}[2] 物理環境（2SW）${C_RESET}"
    echo -e "  ${C_PHY}      TX1=${local_t1p}  TX2=${local_t2p}  TX3=${local_t3p}  CR=${local_crp}${C_RESET}"
    echo ""
    echo -e "  ${C_BOLD}[q] 終了${C_RESET}"
    echo -e "${C_BOLD}══════════════════════════════════════════${C_RESET}"
    read -rp "  選択 > " choice
    case "$choice" in
        1) _edit veth ;;
        2) _edit physical ;;
        q|Q) echo "  終了します"; break ;;
        *) echo -e "  ${C_WARN}1, 2, q で選んでください${C_RESET}" ;;
    esac
done
