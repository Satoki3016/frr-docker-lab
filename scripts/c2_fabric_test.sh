#!/bin/bash
# C2 (3独立経路) ファブリック開通試験
# PC(virttrx)上で実行: sudo bash scripts/c2_fabric_test.sh
#
# 各経路はタグなし専用線のため、VLANサブIF不要で直接IPを振って試験する。
# 経路1(CR1): enp5s0f1      -> SW1:Eth18->Eth17 -> SW2:Eth10->Eth11 -> enp5s0f0
# 経路2(CR2): enp23s0f0np0  -> SW1:Eth16->Eth20 -> SW2:Eth12->Eth7  -> enp23s0f1np1
# 経路3(CR3): enp179s0f0np0 -> SW1:Eth19->Eth0  -> SW2:Eth0->Eth5   -> enp179s0f1np1
set -e

declare -A PAIRS=(
  [1]="enp5s0f1 enp5s0f0"
  [2]="enp23s0f0np0 enp23s0f1np1"
  [3]="enp179s0f0np0 enp179s0f1np1"
)

echo "=== [1] クリーンアップ ==="
for n in c2a1 c2b1 c2a2 c2b2 c2a3 c2b3; do
  ip netns del "$n" 2>/dev/null || true
done

echo "=== [2] MTU 9100 + netns割り当て + IP付与 ==="
for i in 1 2 3; do
  read -r nicA nicB <<< "${PAIRS[$i]}"
  nsA="c2a${i}"; nsB="c2b${i}"
  ip netns add "$nsA"
  ip netns add "$nsB"
  ip link set "$nicA" netns "$nsA"
  ip link set "$nicB" netns "$nsB"
  ip netns exec "$nsA" ip link set "$nicA" up mtu 9100
  ip netns exec "$nsB" ip link set "$nicB" up mtu 9100
  ip netns exec "$nsA" ip addr add 10.99.${i}.1/30 dev "$nicA"
  ip netns exec "$nsB" ip addr add 10.99.${i}.2/30 dev "$nicB"
  ip netns exec "$nsA" ip link set lo up
  ip netns exec "$nsB" ip link set lo up
  echo "  [ok] 経路${i}: $nicA(10.99.${i}.1) <-> $nicB(10.99.${i}.2)"
done

echo ""
echo "=== [3] 疎通確認 (ping) ==="
for i in 1 2 3; do
  echo "--- 経路${i} ---"
  ip netns exec "c2a${i}" ping -c3 -W2 10.99.${i}.2 | tail -3
done

echo ""
echo "=== [4] スループット試験 (同時実行で相互干渉が無いか確認) ==="
for i in 1 2 3; do
  ip netns exec "c2b${i}" pkill iperf3 2>/dev/null || true
done
sleep 1
for i in 1 2 3; do
  ip netns exec "c2b${i}" iperf3 -s -D
done
sleep 1

for i in 1 2 3; do
  ip netns exec "c2a${i}" iperf3 -u -c 10.99.${i}.2 -b 9500M -l 8950 -t 10 -O 2 -J > /tmp/c2_path${i}.json &
done
wait

for i in 1 2 3; do
  echo "--- 経路${i} UDP 9.5G結果 ---"
  python3 -c "
import json
d=json.load(open('/tmp/c2_path${i}.json'))
s=d['end']['sum']
print(f\"  スループット: {s['bytes']*8/s['seconds']/1e9:.3f} Gbps  損失: {s.get('lost_percent',-1):.4f}%\")
"
done

for i in 1 2 3; do
  ip netns exec "c2b${i}" pkill iperf3 2>/dev/null || true
done

echo ""
echo "=== 完了 (netns c2a1/b1〜c2a3/b3 は残置。削除: sudo bash -c 'for n in c2a1 c2b1 c2a2 c2b2 c2a3 c2b3; do ip netns del \$n; done') ==="
