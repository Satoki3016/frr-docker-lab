#!/bin/bash
# C1 ファブリック開通試験
# PC(virttrx)上で実行: sudo bash scripts/c1_fabric_test.sh
#
# 経路: fabA netns → enp5s0f1(VLAN101) → SW1:Eth17 → SW1 ASIC → Eth14
#       → SW2:Eth2 → SW2 ASIC → Eth10 → enp5s0f0(VLAN101) → fabB netns
# 期待値: ジャンボUDP 9.5Gで損失ほぼ0%
set -e

echo "=== [1] クリーンアップ ==="
ip netns del fabA 2>/dev/null || true
ip netns del fabB 2>/dev/null || true
sleep 1

echo "=== [2] netns + VLAN101 サブIF 構成 ==="
ip netns add fabA
ip netns add fabB
ip link set enp5s0f1 up mtu 9100
ip link set enp5s0f0 up mtu 9100
ip link add link enp5s0f1 name f1v101 type vlan id 101
ip link add link enp5s0f0 name f0v101 type vlan id 101
ip link set f1v101 netns fabA
ip link set f0v101 netns fabB
ip netns exec fabA ip link set f1v101 up mtu 9000
ip netns exec fabB ip link set f0v101 up mtu 9000
ip netns exec fabA ip addr add 10.99.1.1/30 dev f1v101
ip netns exec fabB ip addr add 10.99.1.2/30 dev f0v101
ip netns exec fabA ip link set lo up
ip netns exec fabB ip link set lo up
echo "  [ok]"

echo "=== [3] 疎通確認 (ping) ==="
ip netns exec fabA ping -c3 -W2 10.99.1.2 | tail -2

echo ""
echo "=== [4] スループット試験 ==="
ip netns exec fabB pkill iperf3 2>/dev/null || true
sleep 1
ip netns exec fabB iperf3 -s -D
sleep 1

echo "--- TCP (経路の健全性確認) ---"
ip netns exec fabA iperf3 -c 10.99.1.2 -t 8 -O 2 | tail -4

echo "--- UDP 9.5G ジャンボ8950B (本命) ---"
ip netns exec fabA iperf3 -u -c 10.99.1.2 -b 9500M -l 8950 -t 10 -O 2 | tail -4

echo "--- UDP 9.9G 限界確認 ---"
ip netns exec fabA iperf3 -u -c 10.99.1.2 -b 9900M -l 8950 -t 10 -O 2 | tail -4

ip netns exec fabB pkill iperf3 2>/dev/null || true
echo ""
echo "=== 完了 (netns fabA/fabB は残置。削除: sudo ip netns del fabA fabB) ==="
