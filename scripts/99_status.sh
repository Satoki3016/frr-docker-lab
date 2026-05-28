#!/bin/bash
source "$(dirname "$0")/00_env.sh"

echo "=== Namespaces ==="
ip netns list

for node in $NODES; do
    if ! ns_exists "$node"; then
        continue
    fi
    echo ""
    echo "--- $node ---"
    ip netns exec "$node" ip addr show 2>/dev/null | grep -E "inet |^[0-9]"
    echo "  routes:"
    ip netns exec "$node" ip route show 2>/dev/null | sed 's/^/    /'
done
