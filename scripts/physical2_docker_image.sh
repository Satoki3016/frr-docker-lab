#!/bin/bash
# PC上で実行: Docker イメージをスイッチに転送する
# 使い方: bash scripts/physical2_docker_image.sh <SW1_IP> <SW2_IP> [user]
#
# SONiC上では apt 禁止のため、PC の Docker でイメージを取得してスイッチへ転送する
set -e

SW1_IP="${1:?SW1のIPを指定してください}"
SW2_IP="${2:?SW2のIPを指定してください}"
USER="${3:-kannolab}"
IMAGE="nicolaka/netshoot"
TAR="/tmp/netshoot.tar"

echo "=== [PC] イメージ取得: $IMAGE ==="
docker pull "$IMAGE"

echo ""
echo "=== [PC] イメージ保存: $TAR ==="
docker save "$IMAGE" -o "$TAR"
ls -lh "$TAR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "=== [PC→SW1] スクリプト転送 ==="
ssh "${USER}@${SW1_IP}" "mkdir -p ~/scripts"
scp "$SCRIPT_DIR/physical2_docker_sw1.sh" \
    "$SCRIPT_DIR/physical2_docker_down.sh" \
    "$SCRIPT_DIR/lab_config.sh" \
    "${USER}@${SW1_IP}:~/scripts/"

echo ""
echo "=== [PC→SW2] スクリプト転送 ==="
ssh "${USER}@${SW2_IP}" "mkdir -p ~/scripts"
scp "$SCRIPT_DIR/physical2_docker_sw2.sh" \
    "$SCRIPT_DIR/physical2_docker_down.sh" \
    "${USER}@${SW2_IP}:~/scripts/"

echo ""
echo "=== [PC→SW1] イメージ転送 ==="
scp "$TAR" "${USER}@${SW1_IP}:/tmp/netshoot.tar"

echo ""
echo "=== [PC→SW2] イメージ転送 ==="
scp "$TAR" "${USER}@${SW2_IP}:/tmp/netshoot.tar"

echo ""
echo "=== スイッチ上でイメージロード ==="
ssh "${USER}@${SW1_IP}" "docker load -i /tmp/netshoot.tar && echo '[SW1] load完了'"
ssh "${USER}@${SW2_IP}" "docker load -i /tmp/netshoot.tar && echo '[SW2] load完了'"

echo ""
echo "=== 完了 ==="
echo "次のステップ:"
echo "  SW1: sudo bash ~/scripts/physical2_docker_sw1.sh"
echo "  SW2: sudo bash ~/scripts/physical2_docker_sw2.sh"
