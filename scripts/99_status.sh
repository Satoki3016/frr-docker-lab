#!/bin/bash
source "$(dirname "$0")/00_env.sh"

<<<<<<< HEAD
echo "=== Namespaces ==="
ip netns list

for node in $NODES; do
    if ! ns_exists "$node"; then
=======
echo "=== Containers ==="
docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E "NAME|$(echo $NODES | tr ' ' '|')" || true

for node in $NODES; do
    if ! docker ps --format '{{.Names}}' | grep -q "^${node}$"; then
>>>>>>> a871d29236fc25033b139708afa500660335c698
        continue
    fi
    echo ""
    echo "--- $node ---"
<<<<<<< HEAD
    ip netns exec "$node" ip addr show 2>/dev/null | grep -E "inet |^[0-9]"
    echo "  routes:"
    ip netns exec "$node" ip route show 2>/dev/null | sed 's/^/    /'
=======
    docker exec "$node" ip addr show 2>/dev/null | grep -E "inet |^[0-9]"
    echo "  routes:"
    docker exec "$node" ip route show 2>/dev/null | sed 's/^/    /'
>>>>>>> a871d29236fc25033b139708afa500660335c698
done
