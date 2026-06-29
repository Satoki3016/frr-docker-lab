#!/bin/bash
# FRR Docker ラボ 一括起動
# OSPF-SR + DiffServ-TE + TC/HTB QoS
#
# 使い方:
#   sudo bash scripts/frr_all_up.sh
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "████████████████████████████████████████"
echo "  OSPF-SR + DiffServ-TE ラボ 起動"
echo "████████████████████████████████████████"

echo ""
echo "▶ [1/3] コンテナ・配線・OSPF-SR セットアップ"
bash "$SCRIPT_DIR/frr_setup.sh"

echo ""
echo "▶ [2/3] DSCP TE経路 + TC/HTB QoS 設定"
bash "$SCRIPT_DIR/frr_dscp_te.sh"

echo ""
echo "▶ [3/3] 動的TE経路モニター起動"
pkill -f "frr_te_monitor.sh" 2>/dev/null || true
sleep 0.5
bash "$SCRIPT_DIR/frr_te_monitor.sh" /tmp/frr_te_monitor.log &
sleep 1

echo ""
echo "████████████████████████████████████████"
echo "  起動完了"
echo "████████████████████████████████████████"
echo ""
echo "■ 状態確認:"
echo "  docker exec frr-LER_Ingress vtysh -c 'show ip ospf neighbor'"
echo "  docker exec frr-LER_Ingress vtysh -c 'show mpls table'"
echo "  docker exec frr-LER_Ingress ip route show 192.168.0.5/32   # LER_Egress SID確認"
echo "  docker exec LER_Ingress ip route show table 41"
echo ""
echo "■ フェイルオーバーテスト:"
echo "  docker exec LER_Ingress ip link set leri-cr1 down  # CR1障害"
echo "  docker exec LER_Ingress ip link set leri-cr1 up    # 復旧"
echo ""
echo "■ 計測:"
echo "  sudo bash scripts/measure.sh 60 failure_rsvp"
echo ""
echo "■ 停止:"
echo "  sudo bash scripts/frr_down.sh"
