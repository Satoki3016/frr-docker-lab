#!/bin/bash
# Phase 1: LDP（動的ラベル配布）セットアップ (SW1)
# 静的MPLSラベル → LDPによる自動配布に移行
# 前提: physical2_frr_sw1.sh が実行済みであること
# 実行: SW1上で  sudo bash scripts/physical2_ldp_sw1.sh
set -e

FRR_IMAGE="${FRR_IMAGE:-frrouting/frr}"

# Loopback IPアドレス（LDP transport address・OSPF router-id用）
declare -A LO_IP=(
    [LER_Ingress]="10.255.1.1"
    [CR1]="10.255.1.2"
    [CR2]="10.255.1.3"
    [CR3]="10.255.1.4"
)

# ── 1. Loopback IP + MPLSカーネル設定 ────────────────────────────
echo "=== [SW1] Loopback IP / MPLS設定 ==="
for name in LER_Ingress CR1 CR2 CR3; do
    lo="${LO_IP[$name]}"
    docker exec "$name" ip addr add "${lo}/32" dev lo 2>/dev/null || true
    docker exec "$name" sysctl -qw net.mpls.conf.lo.input=1
    echo "  ${name}: lo=${lo}/32  mpls_input=1"
done

# ── 2. 静的MPLSルート削除（LDPが引き継ぐ） ────────────────────
echo ""
echo "=== [SW1] 静的MPLSルート削除 ==="
for dest in 10.20.1.2 10.20.2.2 10.20.3.2; do
    docker exec LER_Ingress ip route flush "${dest}/32" 2>/dev/null || true
done
echo "  [ok] /32 静的MPLSルート削除完了"

# ── 3. FRRコンテナ更新（ldpd有効、OSPF設定のみ） ─────────────────
# 注: LDP設定はfrr.confのaddress-familyパーサが不安定なためvtysh経由で行う
update_frr() {
    local name=$1 router_id=$2 bfd_ifaces=$3
    shift 3
    local ospf_nets=("$@")
    local dir="/tmp/frr-${name}"
    local lo="${LO_IP[$name]}"
    mkdir -p "$dir"

    cat > "${dir}/daemons" << 'DAEMONS'
zebra=yes
ospfd=yes
bfdd=yes
ldpd=yes
staticd=yes
vtysh_enable=yes
DAEMONS

    echo "service integrated-vtysh-config" > "${dir}/vtysh.conf"

    {
        printf "frr version 8.4\nfrr defaults traditional\nhostname %s\nlog syslog informational\n!\n" "$name"
        # インタフェース設定（CR向けのみ; loopbackはnetworkステートメントで追加）
        for iface in $bfd_ifaces; do
            printf "interface %s\n ip ospf bfd\n ip ospf bfd profile fast\n ip ospf hello-interval 1\n ip ospf dead-interval 3\n ip ospf network point-to-point\n!\n" "$iface"
        done
        # BFDプロファイル: 50ms×3=150ms検出（フェイルオーバー最低要件）
        printf "bfd\n profile fast\n  receive-interval 50\n  transmit-interval 50\n  detect-multiplier 3\n !\n!\n"
        # OSPF（networkステートメントのみ; ip ospf areaとの混在は禁止）
        printf "router ospf\n ospf router-id %s\n" "$router_id"
        for net in "${ospf_nets[@]}"; do
            printf " network %s area 0\n" "$net"
        done
        printf " network %s/32 area 0\n" "$lo"
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
    echo "  [ok] frr-${name} (ldpd有効)"
}

configure_ldp() {
    local name=$1 router_id=$2
    shift 2
    local lo="${LO_IP[$name]}"
    {
        echo "configure terminal"
        echo "mpls ldp"
        echo " router-id ${router_id}"
        echo " address-family ipv4"
        echo "  discovery transport-address ${lo}"
        for iface in "$@"; do
            echo "  interface ${iface}"
        done
        echo " exit-address-family"
        echo "end"
        echo "write memory"
    } | docker exec -i "frr-${name}" vtysh
    echo "  [ok] frr-${name} LDP設定"
}

echo ""
echo "=== [SW1] FRRコンテナ更新 ==="

update_frr "LER_Ingress" "10.255.1.1" \
    "leri-cr1 leri-cr2 leri-cr3" \
    "10.10.1.0/30" "10.10.2.0/30" "10.10.3.0/30" \
    "10.0.1.0/30" "10.0.3.0/30" "10.0.5.0/30"

update_frr "CR1" "10.255.1.2" \
    "cr1-leri cr1-lere" \
    "10.0.1.0/30" "10.0.2.0/30"

update_frr "CR2" "10.255.1.3" \
    "cr2-leri cr2-lere" \
    "10.0.3.0/30" "10.0.4.0/30"

update_frr "CR3" "10.255.1.4" \
    "cr3-leri cr3-lere" \
    "10.0.5.0/30" "10.0.6.0/30"

# ── 4. MPLS有効化（各インタフェース） ────────────────────────────
echo ""
echo "=== [SW1] MPLSインタフェース有効化 ==="
for iface in leri-cr1 leri-cr2 leri-cr3; do
    docker exec LER_Ingress sysctl -qw "net.mpls.conf.${iface}.input=1" 2>/dev/null || true
done
for iface in cr1-leri cr1-lere; do
    docker exec CR1 sysctl -qw "net.mpls.conf.${iface}.input=1" 2>/dev/null || true
done
for iface in cr2-leri cr2-lere; do
    docker exec CR2 sysctl -qw "net.mpls.conf.${iface}.input=1" 2>/dev/null || true
done
for iface in cr3-leri cr3-lere; do
    docker exec CR3 sysctl -qw "net.mpls.conf.${iface}.input=1" 2>/dev/null || true
done
echo "  [ok]"

# ── 5. OSPF収束待ち ────────────────────────────────────────────
echo ""
echo "=== [SW1] OSPF収束待ち (20秒) ==="
sleep 20

echo ""
echo "=== [SW1] OSPF状態確認 ==="
docker exec frr-LER_Ingress vtysh -c "show ip ospf neighbor" 2>/dev/null || echo "  (まだ収束中)"

# ── 6. LDP設定（vtysh経由） ─────────────────────────────────────
echo ""
echo "=== [SW1] LDP設定 (vtysh) ==="
configure_ldp "LER_Ingress" "10.255.1.1" leri-cr1 leri-cr2 leri-cr3
configure_ldp "CR1"         "10.255.1.2" cr1-leri cr1-lere
configure_ldp "CR2"         "10.255.1.3" cr2-leri cr2-lere
configure_ldp "CR3"         "10.255.1.4" cr3-leri cr3-lere

# ── 7. LDP収束待ち・確認 ────────────────────────────────────────
echo ""
echo "=== [SW1] LDP収束待ち (15秒) ==="
sleep 15

echo ""
echo "=== [SW1] LDP状態確認 ==="
echo "--- LDP neighbors (LER_Ingress) ---"
docker exec frr-LER_Ingress vtysh -c "show mpls ldp neighbor" 2>/dev/null || \
    echo "  (まだ収束中の場合は少し待ってから再確認)"
echo ""
echo "--- LDP bindings (LER_Ingress) ---"
docker exec frr-LER_Ingress vtysh -c "show mpls ldp binding" 2>/dev/null | head -30 || true
echo ""
echo "--- MPLS転送テーブル (LER_Ingress) ---"
docker exec frr-LER_Ingress vtysh -c "show mpls table" 2>/dev/null | head -20 || true

echo ""
echo "=== [SW1] 完了 ==="
cat << 'USAGE'

■ SW2でも実行: sudo bash ~/scripts/physical2_ldp_sw2.sh

■ 確認コマンド:
  docker exec frr-LER_Ingress vtysh -c "show mpls ldp neighbor"
  docker exec frr-LER_Ingress vtysh -c "show mpls ldp binding"
  docker exec frr-LER_Ingress vtysh -c "show mpls table"

■ LDPが配布するラベルの見方:
  "show mpls ldp binding" の出力:
    10.255.1.5/32  label: <自分が配布>  peer-label: <CR1/2/3から受け取ったラベル>
  LER_IngressはこのラベルをMPLSパケットのpushに使う

■ 疎通確認:
  docker exec Tx1 ping -c3 10.20.1.2
USAGE
