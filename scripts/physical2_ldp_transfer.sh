#!/bin/bash
# 修正済みLDPスクリプトをSW1・SW2に転送する
# 使い方: bash scripts/physical2_ldp_transfer.sh <SW1_IP> <SW2_IP> [user]
set -e

SW1_IP="${1:?SW1のIPを指定してください (例: 192.168.x.x)}"
SW2_IP="${2:?SW2のIPを指定してください (例: 192.168.x.x)}"
USER="${3:-kannolab}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== [PC→SW1] LDP・SR・TI-LFA・診断スクリプト転送 ==="
scp "${SCRIPT_DIR}/physical2_ldp_sw1.sh" \
    "${SCRIPT_DIR}/physical2_ldp_sw2.sh" \
    "${SCRIPT_DIR}/physical2_sr_sw1.sh" \
    "${SCRIPT_DIR}/physical2_sr_sw2.sh" \
    "${SCRIPT_DIR}/physical2_sr_diag.sh" \
    "${SCRIPT_DIR}/physical2_sr_fix_sw1.sh" \
    "${SCRIPT_DIR}/physical2_sr_fix_sw2.sh" \
    "${SCRIPT_DIR}/physical2_sr_fix2_sw1.sh" \
    "${SCRIPT_DIR}/physical2_sr_fix2_sw2.sh" \
    "${SCRIPT_DIR}/physical2_compare.sh" \
    "${SCRIPT_DIR}/physical2_compare_report.sh" \
    "${SCRIPT_DIR}/physical2_tilfa_sw1.sh" \
    "${SCRIPT_DIR}/physical2_tilfa_sw2.sh" \
    "${SCRIPT_DIR}/physical2_tilfa_test.sh" \
    "${USER}@${SW1_IP}:~/scripts/"
echo "  [ok] SW1"

echo ""
echo "=== [PC→SW2] LDP・SR・TI-LFA・診断スクリプト転送 ==="
scp "${SCRIPT_DIR}/physical2_ldp_sw2.sh" \
    "${SCRIPT_DIR}/physical2_sr_sw2.sh" \
    "${SCRIPT_DIR}/physical2_sr_diag.sh" \
    "${SCRIPT_DIR}/physical2_sr_fix_sw2.sh" \
    "${SCRIPT_DIR}/physical2_sr_fix2_sw2.sh" \
    "${SCRIPT_DIR}/physical2_tilfa_sw2.sh" \
    "${USER}@${SW2_IP}:~/scripts/"
echo "  [ok] SW2"

echo ""
echo "=== 転送完了 ==="
echo "実行順序:"
echo "  Phase 1 LDP:"
echo "    1. SW1: sudo bash ~/scripts/physical2_ldp_sw1.sh"
echo "    2. SW2: sudo bash ~/scripts/physical2_ldp_sw2.sh"
echo ""
echo "  Phase 2 SR-MPLS (LDP完了後):"
echo "    3. SW1: sudo bash ~/scripts/physical2_sr_sw1.sh"
echo "    4. SW2: sudo bash ~/scripts/physical2_sr_sw2.sh"
echo ""
echo "  Phase 3 TI-LFA (SR完了後):"
echo "    5. SW1: sudo bash ~/scripts/physical2_tilfa_sw1.sh"
echo "    6. SW2: sudo bash ~/scripts/physical2_tilfa_sw2.sh"
echo "    7. テスト: sudo bash ~/scripts/physical2_tilfa_test.sh"
echo ""
echo "  SR Node SID デバッグ (16001-16005が出ない場合):"
echo "    A. 診断: sudo bash ~/scripts/physical2_sr_diag.sh"
echo "    B. 修正: sudo bash ~/scripts/physical2_sr_fix_sw1.sh  (SW1)"
echo "    C. 修正: sudo bash ~/scripts/physical2_sr_fix_sw2.sh  (SW2)"
