#!/bin/bash
# SONiC用 ラボ終了スクリプト
# CoreRouter namespace 削除 + veth + SONiC IP 設定削除

echo "=== CoreRouter namespace 削除 ==="
for ns in CoreRouter1 CoreRouter2 CoreRouter3; do
    if ip netns list 2>/dev/null | awk '{print $1}' | grep -qxF "$ns"; then
        ip netns del "$ns"
        echo "  [del] $ns"
    fi
done

echo ""
echo "=== veth 削除（namespace削除で自動削除済みのものをroot側も確認）==="
for if in leri-cr1 leri-cr2 leri-cr3 lere-cr1 lere-cr2 lere-cr3; do
    ip link del "$if" 2>/dev/null && echo "  [del] $if" || true
done

echo ""
echo "=== SONiC アクセスポートIP削除 ==="
for pair in "Ethernet0:10.10.1.1/30"  "Ethernet2:10.10.2.1/30"  "Ethernet4:10.10.3.1/30" \
            "Ethernet18:10.20.1.1/30" "Ethernet20:10.20.2.1/30" "Ethernet22:10.20.3.1/30"; do
    eth="${pair%%:*}"
    ip="${pair##*:}"
    config interface ip remove "$eth" "$ip" 2>/dev/null && echo "  [del] $eth: $ip" || true
done

echo ""
echo "=== MPLS / TC クリア ==="
ip route flush cache 2>/dev/null || true
ip -f mpls route flush 2>/dev/null || true
iptables -t mangle -F PREROUTING 2>/dev/null || true
for dev in leri-cr1 leri-cr2 leri-cr3 Ethernet0 Ethernet2 Ethernet4 Ethernet18 Ethernet20 Ethernet22; do
    tc qdisc del dev "$dev" root    2>/dev/null || true
    tc qdisc del dev "$dev" ingress 2>/dev/null || true
done

echo "Done."
