#!/bin/bash
# SR-MPLS Node SID 修正スクリプト (SW2 / LER_Egress)
# 実行: SW2上で  sudo bash scripts/physical2_sr_fix_sw2.sh
set -e

LO_LER_EGRESS="10.255.1.5"
SRGB_LOW=16000
SRGB_HIGH=23999
NODE_MSD=8
SR_INDEX=5
SID=$((SRGB_LOW + SR_INDEX))

SEP="════════════════════════════════════════════"

echo "$SEP"
echo "【Fix 1】ホストカーネル MPLS 設定 (SW2)"

PLAT=$(cat /proc/sys/net/mpls/platform_labels 2>/dev/null || echo "0")
if [ "$PLAT" -eq 0 ] 2>/dev/null; then
    sysctl -w net.mpls.platform_labels=1048575
fi

PID=$(docker inspect --format '{{.State.Pid}}' LER_Egress 2>/dev/null || echo "")
if [ -n "$PID" ]; then
    for iface in $(nsenter -t "$PID" -n -- ip -o link show | awk -F': ' '{print $2}' | grep -v lo); do
        nsenter -t "$PID" -n -- sysctl -w "net.mpls.conf.${iface}.input=1" 2>/dev/null || true
    done
    nsenter -t "$PID" -n -- sysctl -w "net.mpls.conf.lo.input=1" 2>/dev/null || true
fi
echo "  [ok] MPLS kernel"

echo ""
echo "$SEP"
echo "【Fix 2】LER_Egress SR + mpls-te 再設定  SID=${SID}"
{
    echo "configure terminal"
    echo "router ospf"
    echo " mpls-te on"
    echo " mpls-te router-address ${LO_LER_EGRESS}"
    echo " segment-routing on"
    echo " segment-routing global-block ${SRGB_LOW} ${SRGB_HIGH}"
    echo " segment-routing node-msd ${NODE_MSD}"
    echo " segment-routing prefix ${LO_LER_EGRESS}/32 index ${SR_INDEX}"
    echo "exit"
    echo "end"
    echo "write memory"
} | docker exec -i frr-LER_Egress vtysh
echo "  [ok] frr-LER_Egress"

echo ""
echo "SR 収束待ち (20秒) ..."
sleep 20

echo ""
echo "--- MPLS テーブル (LER_Egress) ---"
docker exec frr-LER_Egress vtysh -c "show mpls table" 2>/dev/null || true

echo ""
echo "--- running-config SR (LER_Egress) ---"
docker exec frr-LER_Egress vtysh -c "show running-config" 2>/dev/null | \
    grep -E "segment-routing|mpls-te" | head -10 || true

echo ""
echo "$SEP"
echo "■ SW2 修正完了"
