#!/bin/bash
# AF41/AF42 だけ疎通せず AF43 は通る、という症状を切り分ける。
# 経路・ポリシールーティング・HTB・実際の疎通を、クラスごとに突き合わせる。
echo "############ 1. ポリシールーティング (ip rule) ############"
docker exec LER_Ingress ip rule show

for t in 41 42 43; do
  echo
  echo "############ 2. table $t の経路 ############"
  docker exec LER_Ingress ip route show table $t
done

echo
echo "############ 3. iptables の DSCP→fwmark ############"
docker exec LER_Ingress iptables -t mangle -S 2>/dev/null | grep -iE "dscp|mark" | head -20

echo
echo "############ 4. leri-cr1 の HTB クラス ############"
docker exec LER_Ingress tc -s class show dev leri-cr1 | grep -A3 -E "class htb 1:(0|1|2|3) "

echo
echo "############ 5. leri-cr1 のフィルタ ############"
docker exec LER_Ingress tc filter show dev leri-cr1 | head -20

echo
echo "############ 6. MPLS 転送表 (CR1/CR2/CR3) ############"
for c in CR1 CR2 CR3; do
  printf '  %s: ' "$c"; docker exec "$c" ip -f mpls route show 2>/dev/null | tr '\n' ' '; echo
done

echo
echo "############ 7. 実際の疎通 (各Tx→各Rx) ############"
for i in 1 2 3; do
  case $i in 1) dst=10.20.1.1; port=1000;; 2) dst=10.20.2.1; port=2000;; 3) dst=10.20.3.1; port=3000;; esac
  printf '  Tx%s → Rx%s (%s) ping: ' "$i" "$i" "$dst"
  docker exec "Tx$i" ping -c2 -W2 -q "$dst" 2>&1 | tail -2 | head -1
  printf '  Tx%s → %s:%s TCP: ' "$i" "$dst" "$port"
  docker exec "Tx$i" timeout 4 bash -c "</dev/tcp/$dst/$port" 2>&1 \
      && echo "接続OK" || echo "接続NG"
done

echo
echo "############ 8. Rx 側で iperf3 は待ち受けているか ############"
for i in 1 2 3; do
  printf '  Rx%s: ' "$i"
  docker exec "Rx$i" sh -c 'ss -lntup 2>/dev/null | grep -c iperf3 || echo 0' 2>/dev/null
done
