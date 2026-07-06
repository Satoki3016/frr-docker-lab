#!/bin/bash
# FRR (OSPF+BFD) セットアップ (SW2)
# 前提: physical2_docker_sw2.sh が実行済みであること
# 実行: SW2上で  sudo bash scripts/physical2_frr_sw2.sh
set -e

FRR_IMAGE="${FRR_IMAGE:-frrouting/frr}"

# ── 1. MPLS バックアップラベル受信設定 ───────────────────────────
#
# SW1側のバックアップルート(label 110,120,210,220,310,320)は
# CRでスワップ後に101/201/301になる。
# LER_EgressはSW1セットアップ時点で101→Rx1, 201→Rx2, 301→Rx3を設定済み。
# 追加設定は不要。
echo "=== [SW2] MPLS バックアップ確認 ==="
docker exec LER_Egress ip -f mpls route show
echo "  [ok] 既存ラベル(101→Rx1, 201→Rx2, 301→Rx3)がバックアップルートも兼ねる"

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
echo "=== [SW2] FRR companion コンテナ起動 ==="

start_frr "LER_Egress" "10.0.2.2" \
    "lere-cr1 lere-cr2 lere-cr3" \
    "10.0.2.0/30" "10.0.4.0/30" "10.0.6.0/30" \
    "10.20.1.0/30" "10.20.2.0/30" "10.20.3.0/30"

# ── 4. OSPF収束待ち ───────────────────────────────────────────────
echo ""
echo "=== [SW2] OSPF収束待ち (15秒) ==="
sleep 15

echo ""
echo "=== [SW2] OSPF/BFD 状態確認 ==="
echo "--- LER_Egress OSPF neighbors ---"
docker exec frr-LER_Egress vtysh -c "show ip ospf neighbor" 2>/dev/null || echo "  (まだ収束中の場合があります)"
echo ""
echo "--- LER_Egress BFD peers ---"
docker exec frr-LER_Egress vtysh -c "show bfd peers" 2>/dev/null || true

echo ""
echo "=== [SW2] 完了 ==="
cat << 'USAGE'

■ SW1, SW2両方セットアップ後のフェイルオーバーテスト (SW1で実行):

  # [端末1] 連続ping + タイムスタンプ
  docker exec Tx1 ping -i 0.2 10.20.1.1 | while read l; do echo "$(date +%T.%3N) $l"; done

  # [端末2] CR1障害シミュレーション
  docker exec LER_Ingress ip link set leri-cr1 down
  # BFD 150ms以内に検出 → OSPFがCR1を切り離し → MPLSバックアップ(label 110 via CR2)に切り替え

  # [端末2] CR1回復
  docker exec LER_Ingress ip link set leri-cr1 up

  # OSPFルートの変化を確認
  docker exec frr-LER_Ingress vtysh -c "show ip route ospf"

■ BFD検出時間の計測:
  # CR1をダウンさせてpingロス期間を計測
  # BFDあり: ~150ms (50ms×3)
  # BFDなし(OSPFのみ): ~3秒 (dead-interval)
USAGE
