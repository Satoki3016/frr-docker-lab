#!/bin/bash
# FRR (OSPF+BFD) + MPLS バックアップルート セットアップ (SW1)
# 前提: physical2_docker_sw1.sh が実行済みであること
# 実行: SW1上で  sudo bash scripts/physical2_frr_sw1.sh
set -e

FRR_IMAGE="${FRR_IMAGE:-frrouting/frr}"

# ── 1. MPLS バックアップルート ─────────────────────────────────────
#
# 現状: Rx1→CR1専用(label 100)、Rx2→CR2専用(label 200)、Rx3→CR3専用(label 300)
# 追加: 各Rxに対して他のCR経由のバックアップラベルを割り当て
#
# ラベル計画:
#   Rx1: 100(CR1), 110(CR2), 120(CR3)
#   Rx2: 200(CR2), 210(CR1), 220(CR3)
#   Rx3: 300(CR3), 310(CR1), 320(CR2)
#
# CRでのスワップ先はすべてLER_Egressへの既存ラベル(101/201/301)に統一
echo "=== [SW1] MPLS バックアップルート ==="

# CR2: Rx1バックアップ(110→101), Rx3バックアップ(320→301)
docker exec CR2 ip -f mpls route replace 110 as 101 via inet 10.0.4.2 dev cr2-lere
docker exec CR2 ip -f mpls route replace 320 as 301 via inet 10.0.4.2 dev cr2-lere

# CR3: Rx1バックアップ(120→101), Rx2バックアップ(220→201)
docker exec CR3 ip -f mpls route replace 120 as 101 via inet 10.0.6.2 dev cr3-lere
docker exec CR3 ip -f mpls route replace 220 as 201 via inet 10.0.6.2 dev cr3-lere

# CR1: Rx2バックアップ(210→201), Rx3バックアップ(310→301)
docker exec CR1 ip -f mpls route replace 210 as 201 via inet 10.0.2.2 dev cr1-lere
docker exec CR1 ip -f mpls route replace 310 as 301 via inet 10.0.2.2 dev cr1-lere

# LER_Ingress: バックアップMPLSプッシュルート(metric=2,3)
# Rx1: primary=CR1(label 100,metric1), backup=CR2(label 110,metric2), CR3(label 120,metric3)
docker exec LER_Ingress ip route add 10.20.1.2/32 encap mpls 110 via 10.0.3.2 dev leri-cr2 metric 2 2>/dev/null || true
docker exec LER_Ingress ip route add 10.20.1.2/32 encap mpls 120 via 10.0.5.2 dev leri-cr3 metric 3 2>/dev/null || true

# Rx2: primary=CR2(label 200,metric1), backup=CR1(label 210,metric2), CR3(label 220,metric3)
docker exec LER_Ingress ip route add 10.20.2.2/32 encap mpls 210 via 10.0.1.2 dev leri-cr1 metric 2 2>/dev/null || true
docker exec LER_Ingress ip route add 10.20.2.2/32 encap mpls 220 via 10.0.5.2 dev leri-cr3 metric 3 2>/dev/null || true

# Rx3: primary=CR3(label 300,metric1), backup=CR1(label 310,metric2), CR2(label 320,metric3)
docker exec LER_Ingress ip route add 10.20.3.2/32 encap mpls 310 via 10.0.1.2 dev leri-cr1 metric 2 2>/dev/null || true
docker exec LER_Ingress ip route add 10.20.3.2/32 encap mpls 320 via 10.0.3.2 dev leri-cr2 metric 3 2>/dev/null || true

echo "  [ok] バックアップラベル設定完了"
docker exec LER_Ingress ip route show | grep 10.20

# ── 2. FRR companion コンテナ起動関数 ─────────────────────────────
start_frr() {
    local name=$1 router_id=$2 bfd_ifaces=$3
    shift 3
    local ospf_nets=("$@")
    local dir="/tmp/frr-${name}"
    mkdir -p "$dir"

    cat > "${dir}/daemons" << 'DAEMONS'
zebra=yes
ospfd=yes
bfdd=yes
staticd=yes
vtysh_enable=yes
DAEMONS

    echo "service integrated-vtysh-config" > "${dir}/vtysh.conf"

    {
        printf "frr version 8.4\nfrr defaults traditional\nhostname %s\nlog syslog informational\n!\n" "$name"
        for iface in $bfd_ifaces; do
            printf "interface %s\n ip ospf bfd\n ip ospf hello-interval 1\n ip ospf dead-interval 3\n ip ospf network point-to-point\n!\n" "$iface"
        done
        printf "bfd\n profile fast\n  receive-interval 50\n  transmit-interval 50\n  detect-multiplier 3\n !\n!\n"
        printf "router ospf\n ospf router-id %s\n" "$router_id"
        for net in "${ospf_nets[@]}"; do
            printf " network %s area 0\n" "$net"
        done
        printf "!\n"
    } > "${dir}/frr.conf"

    chmod 777 "$dir"
    chmod 644 "${dir}"/*

    docker rm -f "frr-${name}" 2>/dev/null || true
    docker run -d --name "frr-${name}" \
        --network "container:${name}" \
        --privileged \
        -v "${dir}:/etc/frr" \
        "$FRR_IMAGE"
    echo "  [ok] frr-${name}"
}

# ── 3. FRR コンテナ起動 ───────────────────────────────────────────
echo ""
echo "=== [SW1] FRR companion コンテナ起動 ==="

start_frr "LER_Ingress" "10.0.1.1" \
    "leri-cr1 leri-cr2 leri-cr3" \
    "10.10.1.0/30" "10.10.2.0/30" "10.10.3.0/30" \
    "10.0.1.0/30" "10.0.3.0/30" "10.0.5.0/30"

start_frr "CR1" "10.0.1.2" \
    "cr1-leri cr1-lere" \
    "10.0.1.0/30" "10.0.2.0/30"

start_frr "CR2" "10.0.3.2" \
    "cr2-leri cr2-lere" \
    "10.0.3.0/30" "10.0.4.0/30"

start_frr "CR3" "10.0.5.2" \
    "cr3-leri cr3-lere" \
    "10.0.5.0/30" "10.0.6.0/30"

# ── 4. OSPF収束待ち ───────────────────────────────────────────────
echo ""
echo "=== [SW1] OSPF収束待ち (15秒) ==="
sleep 15

echo ""
echo "=== [SW1] OSPF/BFD 状態確認 ==="
echo "--- LER_Ingress OSPF neighbors ---"
docker exec frr-LER_Ingress vtysh -c "show ip ospf neighbor" 2>/dev/null || echo "  (まだ収束中の場合があります)"
echo ""
echo "--- LER_Ingress BFD peers ---"
docker exec frr-LER_Ingress vtysh -c "show bfd peers" 2>/dev/null || true

echo ""
echo "=== [SW1] 完了 ==="
cat << 'USAGE'

■ SW2でも実行: sudo bash ~/scripts/physical2_frr_sw2.sh

■ 状態確認コマンド:
  docker exec frr-LER_Ingress vtysh -c "show ip ospf neighbor"
  docker exec frr-LER_Ingress vtysh -c "show bfd peers"
  docker exec frr-LER_Ingress vtysh -c "show ip route ospf"

■ フェイルオーバーテスト手順:
  # [端末1] 連続ping
  docker exec Tx1 ping 10.20.1.2

  # [端末2] CR1↔LER_Ingress リンクをダウン (BFDで高速検出)
  docker exec LER_Ingress ip link set leri-cr1 down
  # → pingが数パケット欠落後、CR2経由(label 110→101)で自動回復

  # [端末2] リストア
  docker exec LER_Ingress ip link set leri-cr1 up

■ BFDタイマー: 50ms × 3 = 150ms で障害検出
■ (BFDなし比較) OSPF dead-interval: 3秒
USAGE
