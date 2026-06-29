#!/bin/bash
# 物理2スイッチ構成 テアダウン（SW1・SW2 共通）
# 実行: 各スイッチ上で  sudo bash scripts/physical2_docker_down.sh
set -e

echo "=== コンテナ削除 ==="
for name in Tx1 Tx2 Tx3 LER_Ingress CR1 CR2 CR3 LER_Egress Rx1 Rx2 Rx3; do
    docker rm -f "$name" 2>/dev/null && echo "  [del] $name" || true
done

echo ""
echo "=== bridge 削除 ==="
for i in $(seq 0 14); do
    br="br-Ethernet${i}"
    vr="vr-Ethernet${i}"
    ip link del "$br" 2>/dev/null && echo "  [del] $br" || true
    ip link del "$vr" 2>/dev/null && echo "  [del] $vr" || true
done

echo ""
echo "=== 物理ポートをbridgeから切り離し ==="
for i in $(seq 0 14); do
    eth="Ethernet${i}"
    if ip link show "$eth" &>/dev/null; then
        ip link set "$eth" nomaster 2>/dev/null || true
        ip link set "$eth" down 2>/dev/null || true
    fi
done

echo ""
echo "完了"
