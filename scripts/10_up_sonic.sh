#!/bin/bash
# SONiC用 namespace起動: CoreRouterのみ
# LER_Ingress / LER_Egress は SONiC root namespace で動作するため不要
set -e

echo "=== CoreRouter namespace 作成 ==="
for ns in CoreRouter1 CoreRouter2 CoreRouter3; do
    if ip netns list 2>/dev/null | awk '{print $1}' | grep -qxF "$ns"; then
        echo "  [skip] $ns already exists"
    else
        ip netns add "$ns"
        ip netns exec "$ns" ip link set lo up
        echo "  [ok] $ns"
    fi
    ip netns exec "$ns" sysctl -qw net.ipv4.ip_forward=1
done

sysctl -qw net.ipv4.ip_forward=1
echo "CoreRouter namespaces ready."
