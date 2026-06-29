#!/bin/bash
# PC上で実行: FRR Docker イメージをスイッチに転送する
# 使い方: bash scripts/physical2_frr_image.sh <SW1_IP> <SW2_IP> [user]
set -e

SW1_IP="${1:?SW1のIPを指定してください}"
SW2_IP="${2:?SW2のIPを指定してください}"
USER="${3:-kannolab}"
IMAGE="frrouting/frr"
TAR="/tmp/frr.tar"

echo "=== [PC] FRRイメージ取得: $IMAGE ==="
docker pull "$IMAGE"

echo ""
echo "=== [PC] イメージ保存: $TAR ==="
docker save "$IMAGE" -o "$TAR"
ls -lh "$TAR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "=== [PC→SW1] スクリプト転送 ==="
scp "$SCRIPT_DIR/physical2_frr_sw1.sh" \
    "$SCRIPT_DIR/physical2_frr_sw2.sh" \
    "${USER}@${SW1_IP}:~/scripts/"

echo ""
echo "=== [PC→SW2] スクリプト転送 ==="
scp "$SCRIPT_DIR/physical2_frr_sw2.sh" \
    "${USER}@${SW2_IP}:~/scripts/"

echo ""
echo "=== [PC→SW1] イメージ転送 ==="
scp "$TAR" "${USER}@${SW1_IP}:/tmp/frr.tar"

echo ""
echo "=== [PC→SW2] イメージ転送 ==="
scp "$TAR" "${USER}@${SW2_IP}:/tmp/frr.tar"

echo ""
echo "=== スイッチ上でイメージロード ==="
ssh "${USER}@${SW1_IP}" "docker load -i /tmp/frr.tar && echo '[SW1] FRR load完了'"
ssh "${USER}@${SW2_IP}" "docker load -i /tmp/frr.tar && echo '[SW2] FRR load完了'"

echo ""
echo "=== 完了 ==="
echo "次のステップ:"
echo "  SW2: sudo bash ~/scripts/physical2_frr_sw2.sh   # 先にSW2を起動"
echo "  SW1: sudo bash ~/scripts/physical2_frr_sw1.sh"
