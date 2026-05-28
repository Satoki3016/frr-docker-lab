#!/bin/bash
# namespace 起動: ルーターノードのみ (Tx/RxはvirttrxのNICが担当)
set -e
source "$(dirname "$0")/00_env.sh"

echo "=== namespace 作成 ==="
for node in $NODES; do
    if ns_exists "$node"; then
        echo "  [skip] $node already exists"
    else
        ip netns add "$node"
        ip netns exec "$node" ip link set lo up
        echo "  [ok] $node"
    fi
done

for router in $ROUTERS; do
    ip netns exec "$router" sysctl -qw net.ipv4.ip_forward=1
done

echo "All namespaces ready."
