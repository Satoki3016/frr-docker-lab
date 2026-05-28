#!/bin/bash
<<<<<<< HEAD
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
=======
# Docker コンテナ起動: netns の代わりに各ノードをコンテナとして起動
set -e
source "$(dirname "$0")/00_env.sh"

IMAGE="frr-lab-node"

# イメージが存在しない場合はビルド
if ! docker image inspect "$IMAGE" &>/dev/null; then
    echo "=== Dockerイメージをビルド中 ==="
    docker build -q -t "$IMAGE" "$LAB_DIR"
    echo "  [ok] $IMAGE built"
fi

echo "=== コンテナ起動 ==="
for node in $NODES; do
    if docker ps --format '{{.Names}}' | grep -q "^${node}$"; then
        echo "  [skip] $node already running"
    elif docker ps -a --format '{{.Names}}' | grep -q "^${node}$"; then
        docker start "$node"
        echo "  [start] $node"
    else
        docker run -d \
            --name "$node" \
            --network none \
            --privileged \
            --cap-add NET_ADMIN \
            --cap-add SYS_ADMIN \
            -v "$LAB_DIR:/lab:ro" \
            "$IMAGE"
>>>>>>> a871d29236fc25033b139708afa500660335c698
        echo "  [ok] $node"
    fi
done

<<<<<<< HEAD
for router in $ROUTERS; do
    ip netns exec "$router" sysctl -qw net.ipv4.ip_forward=1
done

echo "All namespaces ready."
=======
# ルーターで IP フォワーディング有効化
for router in $ROUTERS; do
    docker exec "$router" sysctl -qw net.ipv4.ip_forward=1
done

echo "All containers ready."
>>>>>>> a871d29236fc25033b139708afa500660335c698
