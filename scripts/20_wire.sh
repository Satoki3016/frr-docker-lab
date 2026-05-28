#!/bin/bash
# veth ペアをnamespace間に配線して IP アドレスを設定
set -e
source "$(dirname "$0")/00_env.sh"

# veth ペアを作成して namespace に移動（冪等: 既存インターフェースを事前削除）
add_link() {
    local ns1=$1 if1=$2 ip1=$3 ns2=$4 if2=$5 ip2=$6

    # 既存インターフェースをクリーンアップ（namespace内・ホスト上）
    ip netns exec "$ns1" ip link del "$if1" 2>/dev/null || true
    ip netns exec "$ns2" ip link del "$if2" 2>/dev/null || true
    ip link del "$if1" 2>/dev/null || true
    ip link del "$if2" 2>/dev/null || true

    ip link add "$if1" type veth peer name "$if2"
    ip link set "$if1" netns "$ns1"
    ip link set "$if2" netns "$ns2"

    ip netns exec "$ns1" ip addr add "$ip1" dev "$if1"
    ip netns exec "$ns2" ip addr add "$ip2" dev "$if2"
    ip netns exec "$ns1" ip link set "$if1" up
    ip netns exec "$ns2" ip link set "$if2" up
    echo "  [ok] $ns1($if1 $ip1) <-> $ns2($if2 $ip2)"
}

echo "=== Wiring links ==="
#                  NS-A         iface-A    IP-A           NS-B         iface-B    IP-B
add_link  Tx1       tx1-ler    10.0.1.2/30  LER_Ingress  leri-tx1   10.0.1.1/30
add_link  Tx2       tx2-ler    10.0.2.2/30  LER_Ingress  leri-tx2   10.0.2.1/30
add_link  Tx3       tx3-ler    10.0.3.2/30  LER_Ingress  leri-tx3   10.0.3.1/30
add_link  LER_Ingress leri-cr1 10.1.3.1/30  CoreRouter1  cr1-leri   10.1.3.2/30
add_link  LER_Ingress leri-cr2 10.1.4.1/30  CoreRouter2  cr2-leri   10.1.4.2/30
add_link  LER_Ingress leri-cr3 10.1.5.1/30  CoreRouter3  cr3-leri   10.1.5.2/30
add_link  CoreRouter1 cr1-lere 10.2.10.2/30 LER_Egress   lere-cr1   10.2.10.1/30
add_link  CoreRouter2 cr2-lere 10.2.11.2/30 LER_Egress   lere-cr2   10.2.11.1/30
add_link  CoreRouter3 cr3-lere 10.2.12.2/30 LER_Egress   lere-cr3   10.2.12.1/30
add_link  LER_Egress  lere-rx1 10.2.1.1/30  Rx1          rx1-lere   10.2.1.2/30
add_link  LER_Egress  lere-rx2 10.2.2.1/30  Rx2          rx2-lere   10.2.2.2/30
add_link  LER_Egress  lere-rx3 10.2.3.1/30  Rx3          rx3-lere   10.2.3.2/30

echo ""
echo "=== Applying host configs ==="
for h in $HOSTS; do
    ip netns exec "$h" bash "$CONFIGS_DIR/hosts/${h}.sh"
    echo "  [ok] $h"
done

echo ""
echo "=== Applying router static routes ==="
# LER_Ingress
ip netns exec LER_Ingress ip route add 10.2.1.0/24 via 10.1.3.2 metric 1
ip netns exec LER_Ingress ip route add 10.2.1.0/24 via 10.1.4.2 metric 2
ip netns exec LER_Ingress ip route add 10.2.1.0/24 via 10.1.5.2 metric 3
ip netns exec LER_Ingress ip route add 10.2.2.0/24 via 10.1.4.2 metric 1
ip netns exec LER_Ingress ip route add 10.2.2.0/24 via 10.1.5.2 metric 2
ip netns exec LER_Ingress ip route add 10.2.2.0/24 via 10.1.3.2 metric 3
ip netns exec LER_Ingress ip route add 10.2.3.0/24 via 10.1.5.2 metric 1
ip netns exec LER_Ingress ip route add 10.2.3.0/24 via 10.1.4.2 metric 2
ip netns exec LER_Ingress ip route add 10.2.3.0/24 via 10.1.3.2 metric 3
echo "  [ok] LER_Ingress"

ip netns exec CoreRouter1 ip route add 10.0.1.0/24 via 10.1.3.1 metric 1
ip netns exec CoreRouter1 ip route add 10.0.2.0/24 via 10.1.3.1 metric 1
ip netns exec CoreRouter1 ip route add 10.0.3.0/24 via 10.1.3.1 metric 1
ip netns exec CoreRouter1 ip route add 10.2.1.0/24 via 10.2.10.1 metric 1
ip netns exec CoreRouter1 ip route add 10.2.2.0/24 via 10.2.10.1 metric 1
ip netns exec CoreRouter1 ip route add 10.2.3.0/24 via 10.2.10.1 metric 1
ip netns exec CoreRouter1 ip route add default    via 10.2.10.1 metric 10
echo "  [ok] CoreRouter1"

ip netns exec CoreRouter2 ip route add 10.0.1.0/24 via 10.1.4.1 metric 1
ip netns exec CoreRouter2 ip route add 10.0.2.0/24 via 10.1.4.1 metric 1
ip netns exec CoreRouter2 ip route add 10.0.3.0/24 via 10.1.4.1 metric 1
ip netns exec CoreRouter2 ip route add 10.2.1.0/24 via 10.2.11.1 metric 1
ip netns exec CoreRouter2 ip route add 10.2.2.0/24 via 10.2.11.1 metric 1
ip netns exec CoreRouter2 ip route add 10.2.3.0/24 via 10.2.11.1 metric 1
ip netns exec CoreRouter2 ip route add default    via 10.2.11.1 metric 10
echo "  [ok] CoreRouter2"

ip netns exec CoreRouter3 ip route add 10.0.1.0/24 via 10.1.5.1 metric 1
ip netns exec CoreRouter3 ip route add 10.0.2.0/24 via 10.1.5.1 metric 1
ip netns exec CoreRouter3 ip route add 10.0.3.0/24 via 10.1.5.1 metric 1
ip netns exec CoreRouter3 ip route add 10.2.1.0/24 via 10.2.12.1 metric 1
ip netns exec CoreRouter3 ip route add 10.2.2.0/24 via 10.2.12.1 metric 1
ip netns exec CoreRouter3 ip route add 10.2.3.0/24 via 10.2.12.1 metric 1
ip netns exec CoreRouter3 ip route add default    via 10.2.12.1 metric 10
echo "  [ok] CoreRouter3"

ip netns exec LER_Egress ip route add 10.0.1.0/24 via 10.2.10.2 metric 1
ip netns exec LER_Egress ip route add 10.0.2.0/24 via 10.2.10.2 metric 1
ip netns exec LER_Egress ip route add 10.0.3.0/24 via 10.2.10.2 metric 1
ip netns exec LER_Egress ip route add 10.0.1.0/24 via 10.2.11.2 metric 2
ip netns exec LER_Egress ip route add 10.0.2.0/24 via 10.2.11.2 metric 2
ip netns exec LER_Egress ip route add 10.0.3.0/24 via 10.2.11.2 metric 2
ip netns exec LER_Egress ip route add 10.0.1.0/24 via 10.2.12.2 metric 3
ip netns exec LER_Egress ip route add 10.0.2.0/24 via 10.2.12.2 metric 3
ip netns exec LER_Egress ip route add 10.0.3.0/24 via 10.2.12.2 metric 3
ip netns exec LER_Egress ip route add default via 10.2.10.2 metric 10
echo "  [ok] LER_Egress"

echo ""
echo "Done. Test with: ip netns exec Tx1 ping -c3 10.2.1.2"
