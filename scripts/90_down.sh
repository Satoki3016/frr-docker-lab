#!/bin/bash
# ラボ終了: namespace 削除 + bridge クリーンアップ
source "$(dirname "$0")/00_env.sh"

echo "=== namespace 削除 ==="
# namespace を削除すると veth ns 側が消え、root 側 peer も自動削除される
for node in $NODES; do
    if ns_exists "$node"; then
        ip netns del "$node"
        echo "  [del] $node"
    fi
done

echo ""
echo "=== bridge 削除（物理ポートを root ns に戻す）==="
for eth in Ethernet0 Ethernet2 Ethernet4 Ethernet18 Ethernet20 Ethernet22; do
    br="br-${eth,,}"
    if ip link show "$br" &>/dev/null 2>&1; then
        ip link del "$br"
        echo "  [del] $br → $eth が root ns に戻りました"
    fi
done

echo "All namespaces removed."
