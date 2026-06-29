#!/bin/bash
# SR-MPLS Fix 2: ospfd 再起動 (SW2 / LER_Egress)
# 実行: SW2上で  sudo bash scripts/physical2_sr_fix2_sw2.sh
set -e

SEP="════════════════════════════════════════════"

echo "$SEP"
echo "【SW2】MPLS インタフェース input 有効化"
PID=$(docker inspect --format '{{.State.Pid}}' LER_Egress 2>/dev/null || true)
if [ -n "$PID" ]; then
    while IFS= read -r iface; do
        iface="${iface%%@*}"
        [[ -z "$iface" ]] && continue
        nsenter -t "$PID" -n -- sysctl -w "net.mpls.conf.${iface}.input=1" 2>/dev/null \
            && echo "  ${iface}: input=1" || true
    done < <(nsenter -t "$PID" -n -- ip -o link show | awk -F': ' '{print $2}')
fi

echo ""
echo "$SEP"
echo "【SW2】LER_Egress ospfd 再起動"
docker exec frr-LER_Egress sh -c \
    'pid=$(cat /var/run/frr/ospfd.pid 2>/dev/null || pgrep ospfd); [ -n "$pid" ] && kill -TERM $pid' \
    2>/dev/null || docker exec frr-LER_Egress pkill -TERM ospfd 2>/dev/null || true

echo "ospfd 再起動・OSPF 再収束待ち (45秒) ..."
sleep 45

echo ""
echo "--- OSPF neighbor (LER_Egress) ---"
docker exec frr-LER_Egress vtysh -c "show ip ospf neighbor" 2>/dev/null | head -10 || true

echo ""
echo "--- Opaque LSA (LER_Egress) ---"
docker exec frr-LER_Egress vtysh -c "show ip ospf database opaque-area" 2>/dev/null | head -30 || true

echo ""
echo "--- MPLS テーブル (LER_Egress) ---"
docker exec frr-LER_Egress vtysh -c "show mpls table" 2>/dev/null || true

echo ""
echo "$SEP"
echo "■ SW2 完了"
