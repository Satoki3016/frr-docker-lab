#!/bin/bash
# 物理ポートをroot namespaceに戻す
NODES="Tx1 Tx2 Tx3 Rx1 Rx2 Rx3 LER_Ingress LER_Egress CoreRouter1 CoreRouter2 CoreRouter3"

for ns in $NODES; do
    ip netns exec "$ns" ip link show 2>/dev/null \
        | grep -E "^[0-9]+:" \
        | awk -F': ' '{print $2}' \
        | grep -v lo \
        | while read -r iface; do
            ip netns exec "$ns" ip link set "$iface" netns 1 2>/dev/null || true
            echo "  restored: $ns/$iface → root"
        done
done

# namespace削除
for ns in $NODES; do
    ip netns del "$ns" 2>/dev/null || true
done

echo "完了"
echo "Ethernet0-23の確認:"
ip link show | grep -E "Ethernet[0-9]$|Ethernet1[0-9]$|Ethernet2[0-3]$" | awk '{print $2}' | tr -d ':'
