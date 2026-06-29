#!/bin/bash
# FRR Docker ラボ 全停止
set -e
echo "=== FRR ラボ停止 ==="
pkill -f "frr_te_monitor.sh" 2>/dev/null && echo "  [stop] frr_te_monitor" || true
for name in \
    frr-LER_Ingress frr-CR1 frr-CR2 frr-CR3 frr-LER_Egress \
    LER_Ingress CR1 CR2 CR3 LER_Egress Tx1 Tx2 Tx3 Rx1 Rx2 Rx3; do
    docker rm -f "$name" 2>/dev/null && echo "  [del] $name" || true
done
echo "完了"
