#!/bin/bash
# RSVP-TE シミュレーション: 全3リンクECMP + WRR優先制御
#
# 設計:
#   全トラフィッククラス(AF41/42/43)を全3コアリンクにECMP分散
#   各リンクのWRR HTB(30_tc.sh設定)が輻輳時に優先度差を実現
#
#   AF41→Rx1 via CR1: push 100 → swap 100→101 → pop 101
#   AF41→Rx1 via CR2: push 110 → swap 110→111 → pop 111
#   AF41→Rx1 via CR3: push 120 → swap 120→121 → pop 121  ← NEW
#
#   AF42→Rx2 via CR1: push 200 → swap 200→201 → pop 201
#   AF42→Rx2 via CR2: push 200 → swap 200→201 → pop 201
#   AF42→Rx2 via CR3: push 210 → swap 210→211 → pop 211
#
#   AF43→Rx3 via CR1: push 300 → swap 300→301 → pop 301
#   AF43→Rx3 via CR2: push 310 → swap 310→311 → pop 311  ← NEW
#   AF43→Rx3 via CR3: push 300 → swap 300→301 → pop 301
#
# ポリシールーティング:
#   iptables mangle: UDPポート/ICMP入力IF → DSCP → fwmark
#   ip rule: fwmark → table 41/42/43
#   各table: ECMP (nexthop × 3 CoreRouter)

set -e
source "$(dirname "$0")/00_env.sh"
source "$(dirname "$0")/lab_config.sh"

# lab_config.sh の帯域文字列 → kbps 整数値
_rate_to_kbps() {
    local r; r=$(echo "$1" | tr '[:upper:]' '[:lower:]')
    case "$r" in
        *gbit) echo $(( ${r%gbit} * 1000000 )) ;;
        *mbit) echo $(( ${r%mbit} * 1000 )) ;;
        *kbit) echo "${r%kbit}" ;;
        *gbps) echo $(( ${r%gbps} * 1000000 )) ;;
        *mbps) echo $(( ${r%mbps} * 1000 )) ;;
        *kbps) echo "${r%kbps}" ;;
        *g)    echo $(( ${r%g}    * 1000000 )) ;;
        *m)    echo $(( ${r%m}    * 1000 )) ;;
        *k)    echo "${r%k}" ;;
        *)     echo 0 ;;
    esac
}

# ----------------------------------------------------------------
# 0. platform_labels 設定 (最大ラベル値 311 以上に設定)
# ----------------------------------------------------------------
echo "=== MPLS platform_labels 設定 ==="
<<<<<<< HEAD
for node in CoreRouter1_ns CoreRouter2_ns CoreRouter3_ns LER_Ingress_ns LER_Egress_ns; do
    ip netns exec "$node" sysctl -qw net.mpls.platform_labels=1048575
done
ip netns exec LER_Ingress_ns sysctl -qw net.ipv4.fib_multipath_hash_policy=1
=======
for node in CoreRouter1 CoreRouter2 CoreRouter3 LER_Ingress LER_Egress; do
    docker exec "$node" sysctl -qw net.mpls.platform_labels=1048575
done
docker exec LER_Ingress sysctl -qw net.ipv4.fib_multipath_hash_policy=1
>>>>>>> a871d29236fc25033b139708afa500660335c698
echo "  全ノード platform_labels=1048575"

# ----------------------------------------------------------------
# 1. Transit ラベル設定 (全9パス)
# ----------------------------------------------------------------
echo "=== Transit LSP 設定 ==="

# CoreRouter1: AF41(100→101), AF42(200→201), AF43(300→301)
<<<<<<< HEAD
ip netns exec CoreRouter1_ns ip -f mpls route replace 100 as 101 via inet 10.0.2.2 dev cr1-lere
ip netns exec CoreRouter1_ns ip -f mpls route replace 200 as 201 via inet 10.0.2.2 dev cr1-lere
ip netns exec CoreRouter1_ns ip -f mpls route replace 300 as 301 via inet 10.0.2.2 dev cr1-lere
echo "  CR1: 100→101(AF41), 200→201(AF42), 300→301(AF43)"

# CoreRouter2: AF41(110→111), AF42(200→201), AF43(310→311)
ip netns exec CoreRouter2_ns ip -f mpls route replace 110 as 111 via inet 10.0.4.2 dev cr2-lere
ip netns exec CoreRouter2_ns ip -f mpls route replace 200 as 201 via inet 10.0.4.2 dev cr2-lere
ip netns exec CoreRouter2_ns ip -f mpls route replace 310 as 311 via inet 10.0.4.2 dev cr2-lere
echo "  CR2: 110→111(AF41), 200→201(AF42), 310→311(AF43)"

# CoreRouter3: AF41(120→121), AF42(210→211), AF43(300→301)
ip netns exec CoreRouter3_ns ip -f mpls route replace 120 as 121 via inet 10.0.6.2 dev cr3-lere
ip netns exec CoreRouter3_ns ip -f mpls route replace 210 as 211 via inet 10.0.6.2 dev cr3-lere
ip netns exec CoreRouter3_ns ip -f mpls route replace 300 as 301 via inet 10.0.6.2 dev cr3-lere
=======
docker exec CoreRouter1 ip -f mpls route replace 100 as 101 via inet 10.2.10.1 dev cr1-lere
docker exec CoreRouter1 ip -f mpls route replace 200 as 201 via inet 10.2.10.1 dev cr1-lere
docker exec CoreRouter1 ip -f mpls route replace 300 as 301 via inet 10.2.10.1 dev cr1-lere
echo "  CR1: 100→101(AF41), 200→201(AF42), 300→301(AF43)"

# CoreRouter2: AF41(110→111), AF42(200→201), AF43(310→311)
docker exec CoreRouter2 ip -f mpls route replace 110 as 111 via inet 10.2.11.1 dev cr2-lere
docker exec CoreRouter2 ip -f mpls route replace 200 as 201 via inet 10.2.11.1 dev cr2-lere
docker exec CoreRouter2 ip -f mpls route replace 310 as 311 via inet 10.2.11.1 dev cr2-lere
echo "  CR2: 110→111(AF41), 200→201(AF42), 310→311(AF43)"

# CoreRouter3: AF41(120→121), AF42(210→211), AF43(300→301)
docker exec CoreRouter3 ip -f mpls route replace 120 as 121 via inet 10.2.12.1 dev cr3-lere
docker exec CoreRouter3 ip -f mpls route replace 210 as 211 via inet 10.2.12.1 dev cr3-lere
docker exec CoreRouter3 ip -f mpls route replace 300 as 301 via inet 10.2.12.1 dev cr3-lere
>>>>>>> a871d29236fc25033b139708afa500660335c698
echo "  CR3: 120→121(AF41), 210→211(AF42), 300→301(AF43)"

# ----------------------------------------------------------------
# 2. MPLS input 有効化 (全インターフェース)
# ----------------------------------------------------------------
echo ""
echo "=== MPLS input 有効化 ==="
for dev in cr1-leri cr1-lere; do
<<<<<<< HEAD
    ip netns exec CoreRouter1_ns sysctl -qw net.mpls.conf.${dev}.input=1
done
for dev in cr2-leri cr2-lere; do
    ip netns exec CoreRouter2_ns sysctl -qw net.mpls.conf.${dev}.input=1
done
for dev in cr3-leri cr3-lere; do
    ip netns exec CoreRouter3_ns sysctl -qw net.mpls.conf.${dev}.input=1
done
echo "  全CoreRouter 全IF input=1"

for dev in lere-cr1 lere-cr2 lere-cr3; do
    ip netns exec LER_Egress_ns sysctl -qw net.mpls.conf.${dev}.input=1
=======
    docker exec CoreRouter1 sysctl -qw net.mpls.conf.${dev}.input=1
done
for dev in cr2-leri cr2-lere; do
    docker exec CoreRouter2 sysctl -qw net.mpls.conf.${dev}.input=1
done
for dev in cr3-leri cr3-lere; do
    docker exec CoreRouter3 sysctl -qw net.mpls.conf.${dev}.input=1
done
echo "  全CoreRouter 全IF input=1"

# LER_Egress: CoreRouter からのMPLSパケットを受信するために必要
for dev in lere-cr1 lere-cr2 lere-cr3; do
    docker exec LER_Egress sysctl -qw net.mpls.conf.${dev}.input=1
>>>>>>> a871d29236fc25033b139708afa500660335c698
done
echo "  LER_Egress 全IF input=1"

# ----------------------------------------------------------------
# 3. Egress pop 設定 (LER_Egress, 全9パス)
# ----------------------------------------------------------------
echo ""
echo "=== Egress pop 設定 (LER_Egress) ==="

# AF41→Rx1: 3経路
<<<<<<< HEAD
ip netns exec LER_Egress_ns ip -f mpls route replace 101 via inet 10.20.1.1 dev lere-rx1
ip netns exec LER_Egress_ns ip -f mpls route replace 111 via inet 10.20.1.1 dev lere-rx1
ip netns exec LER_Egress_ns ip -f mpls route replace 121 via inet 10.20.1.1 dev lere-rx1
echo "  pop 101,111,121 → 10.20.1.1 (Rx1, AF41)"

# AF42→Rx2: 3経路 (201はCR1/CR2共有, 211はCR3)
ip netns exec LER_Egress_ns ip -f mpls route replace 201 via inet 10.20.2.1 dev lere-rx2
ip netns exec LER_Egress_ns ip -f mpls route replace 211 via inet 10.20.2.1 dev lere-rx2
echo "  pop 201,211 → 10.20.2.1 (Rx2, AF42)"

# AF43→Rx3: 3経路 (301はCR1/CR3共有, 311はCR2)
ip netns exec LER_Egress_ns ip -f mpls route replace 301 via inet 10.20.3.1 dev lere-rx3
ip netns exec LER_Egress_ns ip -f mpls route replace 311 via inet 10.20.3.1 dev lere-rx3
echo "  pop 301,311 → 10.20.3.1 (Rx3, AF43)"
=======
docker exec LER_Egress ip -f mpls route replace 101 via inet 10.2.1.2 dev lere-rx1
docker exec LER_Egress ip -f mpls route replace 111 via inet 10.2.1.2 dev lere-rx1
docker exec LER_Egress ip -f mpls route replace 121 via inet 10.2.1.2 dev lere-rx1
echo "  pop 101,111,121 → 10.2.1.2 (Rx1, AF41)"

# AF42→Rx2: 3経路 (201はCR1/CR2共有, 211はCR3)
docker exec LER_Egress ip -f mpls route replace 201 via inet 10.2.2.2 dev lere-rx2
docker exec LER_Egress ip -f mpls route replace 211 via inet 10.2.2.2 dev lere-rx2
echo "  pop 201,211 → 10.2.2.2 (Rx2, AF42)"

# AF43→Rx3: 3経路 (301はCR1/CR3共有, 311はCR2)
docker exec LER_Egress ip -f mpls route replace 301 via inet 10.2.3.2 dev lere-rx3
docker exec LER_Egress ip -f mpls route replace 311 via inet 10.2.3.2 dev lere-rx3
echo "  pop 301,311 → 10.2.3.2 (Rx3, AF43)"
>>>>>>> a871d29236fc25033b139708afa500660335c698

# ----------------------------------------------------------------
# 4. iptables: DSCP マーキング + fwmark
# ----------------------------------------------------------------
echo ""
echo "=== iptables DSCP + fwmark 設定 ==="
<<<<<<< HEAD
ip netns exec LER_Ingress_ns iptables -t mangle -F PREROUTING 2>/dev/null || true

# UDP: dport でDSCP設定
ip netns exec LER_Ingress_ns iptables -t mangle -A PREROUTING \
    -p udp --dport 1000 -j DSCP --set-dscp-class AF41
ip netns exec LER_Ingress_ns iptables -t mangle -A PREROUTING \
    -p udp --dport 2000 -j DSCP --set-dscp-class AF42
ip netns exec LER_Ingress_ns iptables -t mangle -A PREROUTING \
    -p udp --dport 3000 -j DSCP --set-dscp-class AF43

# ICMP: 入力インターフェースでDSCP設定
ip netns exec LER_Ingress_ns iptables -t mangle -A PREROUTING \
    -i enp23s0f1np1 -p icmp -j DSCP --set-dscp-class AF41
ip netns exec LER_Ingress_ns iptables -t mangle -A PREROUTING \
    -i enp179s0f1np1 -p icmp -j DSCP --set-dscp-class AF42
ip netns exec LER_Ingress_ns iptables -t mangle -A PREROUTING \
    -i enp5s0f1 -p icmp -j DSCP --set-dscp-class AF43

# DSCP → fwmark
ip netns exec LER_Ingress_ns iptables -t mangle -A PREROUTING \
    -m dscp --dscp-class AF41 -j MARK --set-mark 41
ip netns exec LER_Ingress_ns iptables -t mangle -A PREROUTING \
    -m dscp --dscp-class AF42 -j MARK --set-mark 42
ip netns exec LER_Ingress_ns iptables -t mangle -A PREROUTING \
=======
docker exec LER_Ingress iptables -t mangle -F PREROUTING 2>/dev/null || true

# UDP: dport でDSCP設定
docker exec LER_Ingress iptables -t mangle -A PREROUTING \
    -p udp --dport 1000 -j DSCP --set-dscp-class AF41
docker exec LER_Ingress iptables -t mangle -A PREROUTING \
    -p udp --dport 2000 -j DSCP --set-dscp-class AF42
docker exec LER_Ingress iptables -t mangle -A PREROUTING \
    -p udp --dport 3000 -j DSCP --set-dscp-class AF43

# ICMP: 入力インターフェースでDSCP設定
docker exec LER_Ingress iptables -t mangle -A PREROUTING \
    -i leri-tx1 -p icmp -j DSCP --set-dscp-class AF41
docker exec LER_Ingress iptables -t mangle -A PREROUTING \
    -i leri-tx2 -p icmp -j DSCP --set-dscp-class AF42
docker exec LER_Ingress iptables -t mangle -A PREROUTING \
    -i leri-tx3 -p icmp -j DSCP --set-dscp-class AF43

# DSCP → fwmark
docker exec LER_Ingress iptables -t mangle -A PREROUTING \
    -m dscp --dscp-class AF41 -j MARK --set-mark 41
docker exec LER_Ingress iptables -t mangle -A PREROUTING \
    -m dscp --dscp-class AF42 -j MARK --set-mark 42
docker exec LER_Ingress iptables -t mangle -A PREROUTING \
>>>>>>> a871d29236fc25033b139708afa500660335c698
    -m dscp --dscp-class AF43 -j MARK --set-mark 43
echo "  UDP(dport 1000/2000/3000) + ICMP(leri-tx1/2/3) → AF41/42/43 → mark 41/42/43"

# ----------------------------------------------------------------
# 5. ポリシールーティングテーブル登録
# ----------------------------------------------------------------
echo ""
echo "=== ポリシールーティングテーブル登録 ==="
<<<<<<< HEAD
grep -q '^41 ' /etc/iproute2/rt_tables || echo '41 rt_af41' >> /etc/iproute2/rt_tables
grep -q '^42 ' /etc/iproute2/rt_tables || echo '42 rt_af42' >> /etc/iproute2/rt_tables
grep -q '^43 ' /etc/iproute2/rt_tables || echo '43 rt_af43' >> /etc/iproute2/rt_tables

# 既存ルール削除
ip netns exec LER_Ingress_ns bash -c "
=======
docker exec LER_Ingress bash -c "
    grep -q '^41 ' /etc/iproute2/rt_tables || echo '41 rt_af41' >> /etc/iproute2/rt_tables
    grep -q '^42 ' /etc/iproute2/rt_tables || echo '42 rt_af42' >> /etc/iproute2/rt_tables
    grep -q '^43 ' /etc/iproute2/rt_tables || echo '43 rt_af43' >> /etc/iproute2/rt_tables
"

# 既存ルール削除
docker exec LER_Ingress bash -c "
>>>>>>> a871d29236fc25033b139708afa500660335c698
    ip rule list | grep -E 'fwmark (0x29|0x2a|0x2b)' | while IFS= read -r line; do
        prio=\$(echo \"\$line\" | cut -d: -f1)
        ip rule del priority \$prio 2>/dev/null || true
    done
" 2>/dev/null || true

<<<<<<< HEAD
ip netns exec LER_Ingress_ns ip rule add fwmark 41 table 41 priority 100
ip netns exec LER_Ingress_ns ip rule add fwmark 42 table 42 priority 100
ip netns exec LER_Ingress_ns ip rule add fwmark 43 table 43 priority 100
=======
docker exec LER_Ingress ip rule add fwmark 41 table 41 priority 100
docker exec LER_Ingress ip rule add fwmark 42 table 42 priority 100
docker exec LER_Ingress ip rule add fwmark 43 table 43 priority 100
>>>>>>> a871d29236fc25033b139708afa500660335c698
echo "  fwmark 41→table41, 42→table42, 43→table43"

# ----------------------------------------------------------------
# 6. ECMP ルーティング (全3リンク)
# ----------------------------------------------------------------
echo ""
echo "=== ECMP ルーティング設定 (LER_Ingress) ==="

<<<<<<< HEAD
ip netns exec LER_Ingress_ns ip route flush table 41 2>/dev/null || true
ip netns exec LER_Ingress_ns ip route flush table 42 2>/dev/null || true
ip netns exec LER_Ingress_ns ip route flush table 43 2>/dev/null || true

# AF41 → Rx1: ECMP 3経路
ip netns exec LER_Ingress_ns ip route replace table 41 10.20.1.1/32 \
    nexthop encap mpls 100 via 10.0.1.2 dev leri-cr1 \
    nexthop encap mpls 110 via 10.0.3.2 dev leri-cr2 \
    nexthop encap mpls 120 via 10.0.5.2 dev leri-cr3
echo "  table41 (AF41): ECMP via CR1(100)[PRIMARY]+CR2(110)+CR3(120)"

# AF42 → Rx2: CR1(label200) + CR2(label200) + CR3(label210) ECMP
ip netns exec LER_Ingress_ns ip route replace table 42 10.20.2.1/32 \
    nexthop encap mpls 200 via 10.0.1.2 dev leri-cr1 \
    nexthop encap mpls 200 via 10.0.3.2 dev leri-cr2 \
    nexthop encap mpls 210 via 10.0.5.2 dev leri-cr3
echo "  table42 (AF42): Rx2 ECMP via CR1(200)+CR2(200)+CR3(210)"

# AF43 → Rx3: CR1(label300) + CR2(label310) + CR3(label300) ECMP
ip netns exec LER_Ingress_ns ip route replace table 43 10.20.3.1/32 \
    nexthop encap mpls 300 via 10.0.1.2 dev leri-cr1 \
    nexthop encap mpls 310 via 10.0.3.2 dev leri-cr2 \
    nexthop encap mpls 300 via 10.0.5.2 dev leri-cr3
=======
# 旧ルートをフラッシュ
docker exec LER_Ingress ip route flush table 41 2>/dev/null || true
docker exec LER_Ingress ip route flush table 42 2>/dev/null || true
docker exec LER_Ingress ip route flush table 43 2>/dev/null || true

# AF41 → Rx1: ECMP 3経路 (CR1=指定プライマリ, CR2/CR3=バックアップ)
#   CR1 障害時: rsvp_monitor が CR1 を除外し CR2+CR3 で継続 (MPLS-TE FRR)
docker exec LER_Ingress ip route replace table 41 10.2.1.2/32 \
    nexthop encap mpls 100 via 10.1.3.2 dev leri-cr1 \
    nexthop encap mpls 110 via 10.1.4.2 dev leri-cr2 \
    nexthop encap mpls 120 via 10.1.5.2 dev leri-cr3
echo "  table41 (AF41): ECMP via CR1(100)[PRIMARY]+CR2(110)+CR3(120)  CR1障害時FRR"

# AF42 → Rx2: CR1(label200) + CR2(label200) + CR3(label210) ECMP
docker exec LER_Ingress ip route replace table 42 10.2.2.2/32 \
    nexthop encap mpls 200 via 10.1.3.2 dev leri-cr1 \
    nexthop encap mpls 200 via 10.1.4.2 dev leri-cr2 \
    nexthop encap mpls 210 via 10.1.5.2 dev leri-cr3
echo "  table42 (AF42): Rx2 ECMP via CR1(200)+CR2(200)+CR3(210)"

# AF43 → Rx3: CR1(label300) + CR2(label310) + CR3(label300) ECMP
docker exec LER_Ingress ip route replace table 43 10.2.3.2/32 \
    nexthop encap mpls 300 via 10.1.3.2 dev leri-cr1 \
    nexthop encap mpls 310 via 10.1.4.2 dev leri-cr2 \
    nexthop encap mpls 300 via 10.1.5.2 dev leri-cr3
>>>>>>> a871d29236fc25033b139708afa500660335c698
echo "  table43 (AF43): Rx3 ECMP via CR1(300)+CR2(310)+CR3(300)"

# ----------------------------------------------------------------
# 7. 確認
# ----------------------------------------------------------------
echo ""
echo "=== 設定確認 ==="
echo "--- ip rule ---"
<<<<<<< HEAD
ip netns exec LER_Ingress_ns ip rule list | grep -E "fwmark|table (41|42|43)"

echo ""
echo "--- table 41 (AF41) ---"
ip netns exec LER_Ingress_ns ip route show table 41

echo ""
echo "--- table 42 (AF42) ---"
ip netns exec LER_Ingress_ns ip route show table 42

echo ""
echo "--- table 43 (AF43) ---"
ip netns exec LER_Ingress_ns ip route show table 43
=======
docker exec LER_Ingress ip rule list | grep -E "fwmark|table (41|42|43)"

echo ""
echo "--- table 41 (AF41) ---"
docker exec LER_Ingress ip route show table 41

echo ""
echo "--- table 42 (AF42) ---"
docker exec LER_Ingress ip route show table 42

echo ""
echo "--- table 43 (AF43) ---"
docker exec LER_Ingress ip route show table 43
>>>>>>> a871d29236fc25033b139708afa500660335c698

echo ""
echo "=== RSVP-TE (ECMP) 設定完了 ==="
echo ""
echo "MPLS-TE 設計:"
echo "  AF41: ECMP CR1[PRIMARY]+CR2+CR3  CR1障害時→FRRでCR2+CR3継続"
echo "  AF42: ECMP via CR1(200)+CR2(200)+CR3(210)"
echo "  AF43: ECMP via CR1(300)+CR2(310)+CR3(300)"
echo ""
echo "理論スループット (正常時, 全3リンク):"
echo "  AF41: 4/7 × 100Mbps × 3リンク = 171 Mbps"
echo "  AF42: 2/7 × 100Mbps × 3リンク =  86 Mbps"
echo "  AF43: 1/7 × 100Mbps × 3リンク =  43 Mbps"
echo ""
echo "CR1 障害時 (failure_rsvp: MPLS-TE FRR):"
echo "  AF41: FRRでCR2+CR3 → 2/3 × 171 = 114 Mbps (優先度制御維持)"
echo "  AF42: ECMP CR2+CR3 → 2/3 ×  86 =  57 Mbps"
echo "  AF43: ECMP CR2+CR3 → 2/3 ×  43 =  29 Mbps"
