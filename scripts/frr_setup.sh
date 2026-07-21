#!/bin/bash
# OSPF-SR + DiffServ-TE ラボ セットアップ
#
# アーキテクチャ:
#   Tx1/2/3 → [veth] → LER_Ingress → [veth] → CR1/2/3 → [veth] → LER_Egress → [veth] → Rx1/2/3
#
# Dockerパターン: main container(nicolaka/netshoot) + FRR companion(frrouting/frr)
#   companion は --network container:<main> でネットワーク名前空間を共有
#   → FRRがvethインタフェースを直接見える
#
# SONiC移行マッピング:
#   veth leri-tx1  → SONiC SW1 Ethernet0  (Tx1アクセスポート)
#   veth leri-tx2  → SONiC SW1 Ethernet2  (Tx2アクセスポート)
#   veth leri-tx3  → SONiC SW1 Ethernet4  (Tx3アクセスポート)
#   veth leri-cr1  → 物理ケーブル SW1→CR1筐体
#   veth leri-cr2  → 物理ケーブル SW1→CR2筐体
#   veth leri-cr3  → 物理ケーブル SW1→CR3筐体
#   (CR/LER_Egress側も同様)
#
# SR-MPLS ラベル計画 (SRGB 16000-23999):
#   LER_Ingress SID index 1  → label 16001  lo=192.168.0.1/32
#   CR1         SID index 2  → label 16002  lo=192.168.0.2/32
#   CR2         SID index 3  → label 16003  lo=192.168.0.3/32
#   CR3         SID index 4  → label 16004  lo=192.168.0.4/32
#   LER_Egress  SID index 5  → label 16005  lo=192.168.0.5/32

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lab_config.sh"

LAB_IMAGE="${LAB_IMAGE:-nicolaka/netshoot}"
FRR_IMAGE="${FRR_IMAGE:-frrouting/frr}"

# コンテナPIDを取得
pid_of() { docker inspect -f '{{.State.Pid}}' "$1"; }
# コンテナのnamed netnsを /var/run/netns/<name> に登録
register_netns() {
    local cname=$1
    local pid; pid=$(pid_of "$cname")
    mkdir -p /var/run/netns
    ln -sf "/proc/${pid}/ns/net" "/var/run/netns/${cname}"
}
# コンテナのネットワーク名前空間でコマンド実行
nse() { ip netns exec "$1" "${@:2}"; }

# ── 1. 既存コンテナ削除 ───────────────────────────────────────────────
echo "=== [1] 既存コンテナ削除 ==="
for name in \
    frr-LER_Ingress frr-CR1 frr-CR2 frr-CR3 frr-LER_Egress \
    LER_Ingress CR1 CR2 CR3 LER_Egress \
    Tx1 Tx2 Tx3 Rx1 Rx2 Rx3; do
    docker rm -f "$name" 2>/dev/null && echo "  [del] $name" || true
    # named netns symlink を削除（コンテナNS消滅に合わせて除去）
    rm -f "/var/run/netns/${name}"
done

# ── 2. カーネルモジュール ─────────────────────────────────────────────
echo ""
echo "=== [2] カーネルモジュール ==="
modprobe mpls_router   2>/dev/null || true
modprobe mpls_iptunnel 2>/dev/null || true
modprobe xt_DSCP       2>/dev/null || true
modprobe xt_mark       2>/dev/null || true
sysctl -qw net.ipv4.ip_forward=1
sysctl -qw net.mpls.platform_labels=65536
echo "  [ok]"

# ── 3. mainコンテナ起動 ────────────────────────────────────────────────
echo ""
echo "=== [3] mainコンテナ起動 (${LAB_IMAGE}) ==="
for name in LER_Ingress CR1 CR2 CR3 LER_Egress Tx1 Tx2 Tx3 Rx1 Rx2 Rx3; do
    docker run -d --name "$name" \
        --network none \
        --privileged \
        --cap-add NET_ADMIN \
        --cap-add NET_RAW \
        --cap-add SYS_MODULE \
        "$LAB_IMAGE" sleep infinity
    echo "  [ok] $name"
done

# ── 3.5. named netns 登録 ──────────────────────────────────────────────
echo ""
echo "=== [3.5] named netns 登録 (ip netns exec 対応) ==="
for name in LER_Ingress CR1 CR2 CR3 LER_Egress Tx1 Tx2 Tx3 Rx1 Rx2 Rx3; do
    register_netns "$name"
    echo "  [ok] /var/run/netns/$name → $(readlink /var/run/netns/$name)"
done

# ── 4. veth配線 ─────────────────────────────────────────────────────
echo ""
echo "=== [4] veth配線 ==="

wire() {
    local c1=$1 if1=$2 ip1=$3 c2=$4 if2=$5 ip2=$6
    # 4箇所でクリーンアップ: 両NSとホストNS (冪等化)
    ip netns exec "$c1" ip link del "$if1" 2>/dev/null || true
    ip netns exec "$c2" ip link del "$if2" 2>/dev/null || true
    ip link del "$if1" 2>/dev/null || true
    ip link del "$if2" 2>/dev/null || true
    # veth作成 → 各コンテナNSへ移動
    ip link add "$if1" type veth peer name "$if2"
    ip link set "$if1" netns "$c1"
    ip link set "$if2" netns "$c2"
    # txqueuelen増加 (netem遅延バッファが veth TX queue 溢れを起こさないよう)
    ip netns exec "$c1" ip link set "$if1" txqueuelen 10000 mtu 9000
    ip netns exec "$c2" ip link set "$if2" txqueuelen 10000 mtu 9000
    ip netns exec "$c1" ip addr add "$ip1" dev "$if1"
    ip netns exec "$c1" ip link set "$if1" up
    ip netns exec "$c2" ip addr add "$ip2" dev "$if2"
    ip netns exec "$c2" ip link set "$if2" up
    echo "  [ok] $c1($if1 $ip1) <-> $c2($if2 $ip2)"
}

# C1物理ファブリック配線 (C1_FABRIC=1 のとき使用)
# コアリンクを 10G NIC → SW1 ASIC → クロスケーブル → SW2 ASIC → 10G NIC 経由にする。
# VLAN 101/102/103 で3リンクを論理分離 (両SWにタグ付きトランク設定済み)。
# 検証: 2026-07-16 c1_fabric_test.sh で 38GB 無損失を確認。
C1_NIC_SW1="${C1_NIC_SW1:-enp5s0f1}"   # SW1:Ethernet17 に結線
C1_NIC_SW2="${C1_NIC_SW2:-enp5s0f0}"   # SW2:Ethernet10 に結線

wire_fabric() {
    local c1=$1 if1=$2 ip1=$3 c2=$4 if2=$5 ip2=$6 vlan=$7
    # 既存サブIF・同名IFのクリーンアップ (冪等化)
    ip netns exec "$c1" ip link del "$if1" 2>/dev/null || true
    ip netns exec "$c2" ip link del "$if2" 2>/dev/null || true
    ip link del "tmpv1-${vlan}" 2>/dev/null || true
    ip link del "tmpv2-${vlan}" 2>/dev/null || true
    # VLANサブIF作成 → 各コンテナNSへ移動・リネーム
    ip link add link "$C1_NIC_SW1" name "tmpv1-${vlan}" address "02:c1:00:01:00:$(printf '%02x' "$vlan")" type vlan id "$vlan"
    ip link add link "$C1_NIC_SW2" name "tmpv2-${vlan}" address "02:c1:00:02:00:$(printf '%02x' "$vlan")" type vlan id "$vlan"
    ip link set "tmpv1-${vlan}" netns "$c1"
    ip link set "tmpv2-${vlan}" netns "$c2"
    ip netns exec "$c1" ip link set "tmpv1-${vlan}" name "$if1"
    ip netns exec "$c2" ip link set "tmpv2-${vlan}" name "$if2"
    ip netns exec "$c1" ip link set "$if1" txqueuelen 10000 mtu 9000
    ip netns exec "$c2" ip link set "$if2" txqueuelen 10000 mtu 9000
    ip netns exec "$c1" ip addr add "$ip1" dev "$if1"
    ip netns exec "$c1" ip link set "$if1" up
    ip netns exec "$c2" ip addr add "$ip2" dev "$if2"
    ip netns exec "$c2" ip link set "$if2" up
    echo "  [ok] $c1($if1 $ip1) <=VLAN${vlan}/物理ファブリック=> $c2($if2 $ip2)"
}

# C2完全独立3経路配線 (LAB_MODE=c2 のとき使用)
# 各コアリンクに専用の物理NICペアを割り当てる(VLANタグ不要)。
# 検証: 2026-07-21 flapテストで9本全て確認済み。config_db.jsonにVLAN201/202/203設定済み(SW1/SW2)。
# 参照: memory project_c2_independent_paths.md の最終配線表
declare -A C2_NIC_SW1=( [1]="enp5s0f1"     [2]="enp23s0f0np0"  [3]="enp179s0f0np0" )
declare -A C2_NIC_SW2=( [1]="enp5s0f0"     [2]="enp23s0f1np1"  [3]="enp179s0f1np1" )

# NICが現在どのnetnsにいても確実にrootへ戻す(netns churnでの迷子対策)
_ensure_nic_in_root() {
    local nic=$1
    ip link show "$nic" >/dev/null 2>&1 && return 0   # 既にroot
    for ns in $(ip netns list | awk '{print $1}'); do
        if ip netns exec "$ns" ip link show "$nic" >/dev/null 2>&1; then
            ip netns exec "$ns" ip link set "$nic" netns 1
            return 0
        fi
    done
}

wire_fabric_c2() {
    local c1=$1 if1=$2 ip1=$3 nic1=$4 c2=$5 if2=$6 ip2=$7 nic2=$8
    ip netns exec "$c1" ip link del "$if1" 2>/dev/null || true
    ip netns exec "$c2" ip link del "$if2" 2>/dev/null || true
    _ensure_nic_in_root "$nic1"
    _ensure_nic_in_root "$nic2"
    ip link set "$nic1" netns "$c1"
    ip link set "$nic2" netns "$c2"
    ip netns exec "$c1" ip link set "$nic1" name "$if1"
    ip netns exec "$c2" ip link set "$nic2" name "$if2"
    ip netns exec "$c1" ip link set "$if1" txqueuelen 10000 mtu 9100
    ip netns exec "$c2" ip link set "$if2" txqueuelen 10000 mtu 9100
    ip netns exec "$c1" ip addr add "$ip1" dev "$if1"
    ip netns exec "$c1" ip link set "$if1" up
    ip netns exec "$c2" ip addr add "$ip2" dev "$if2"
    ip netns exec "$c2" ip link set "$if2" up
    echo "  [ok] $c1($if1 $ip1) <=専用物理リンク($nic1<->$nic2)=> $c2($if2 $ip2)"
}

# Tx ↔ LER_Ingress
wire Tx1 tx1-leri 10.10.1.1/30  LER_Ingress leri-tx1 10.10.1.2/30
wire Tx2 tx2-leri 10.10.2.1/30  LER_Ingress leri-tx2 10.10.2.2/30
wire Tx3 tx3-leri 10.10.3.1/30  LER_Ingress leri-tx3 10.10.3.2/30
# LER_Ingress ↔ CoreRouters
wire LER_Ingress leri-cr1 10.0.1.1/30  CR1 cr1-leri 10.0.1.2/30
wire LER_Ingress leri-cr2 10.0.3.1/30  CR2 cr2-leri 10.0.3.2/30
wire LER_Ingress leri-cr3 10.0.5.1/30  CR3 cr3-leri 10.0.5.2/30
# CoreRouters ↔ LER_Egress
if [ "${LAB_MODE:-}" = "c2" ]; then
    echo "  -- C2完全独立3経路モード --"
    # 開通試験のnetns残骸をクリーンアップ (物理NICの迷子防止)
    for n in fabA fabB c2a1 c2b1 c2a2 c2b2 c2a3 c2b3; do
        ip netns del "$n" 2>/dev/null || true
    done
    wire_fabric_c2 CR1 cr1-lere 10.0.2.1/30 "${C2_NIC_SW1[1]}"  LER_Egress lere-cr1 10.0.2.2/30 "${C2_NIC_SW2[1]}"
    wire_fabric_c2 CR2 cr2-lere 10.0.4.1/30 "${C2_NIC_SW1[2]}"  LER_Egress lere-cr2 10.0.4.2/30 "${C2_NIC_SW2[2]}"
    wire_fabric_c2 CR3 cr3-lere 10.0.6.1/30 "${C2_NIC_SW1[3]}"  LER_Egress lere-cr3 10.0.6.2/30 "${C2_NIC_SW2[3]}"
elif [ "${C1_FABRIC:-0}" = "1" ] || [ "${LAB_MODE:-}" = "c1" ]; then
    echo "  -- C1物理ファブリックモード (${C1_NIC_SW1}/${C1_NIC_SW2}) --"
    # 開通試験のnetns残骸をクリーンアップ (VLAN 101が衝突するため)
    ip netns del fabA 2>/dev/null || true
    ip netns del fabB 2>/dev/null || true
    ip link set "$C1_NIC_SW1" up mtu 9100
    ip link set "$C1_NIC_SW2" up mtu 9100
    wire_fabric CR1 cr1-lere 10.0.2.1/30  LER_Egress lere-cr1 10.0.2.2/30  101
    wire_fabric CR2 cr2-lere 10.0.4.1/30  LER_Egress lere-cr2 10.0.4.2/30  102
    wire_fabric CR3 cr3-lere 10.0.6.1/30  LER_Egress lere-cr3 10.0.6.2/30  103
else
    wire CR1 cr1-lere 10.0.2.1/30  LER_Egress lere-cr1 10.0.2.2/30
    wire CR2 cr2-lere 10.0.4.1/30  LER_Egress lere-cr2 10.0.4.2/30
    wire CR3 cr3-lere 10.0.6.1/30  LER_Egress lere-cr3 10.0.6.2/30
fi
# LER_Egress ↔ Rx
wire LER_Egress lere-rx1 10.20.1.2/30  Rx1 rx1-lere 10.20.1.1/30
wire LER_Egress lere-rx2 10.20.2.2/30  Rx2 rx2-lere 10.20.2.1/30
wire LER_Egress lere-rx3 10.20.3.2/30  Rx3 rx3-lere 10.20.3.1/30

# ── 5. ループバック・MPLS有効化 ────────────────────────────────────────
echo ""
echo "=== [5] ループバック・MPLS設定 ==="
declare -A LO_IP=(
    [LER_Ingress]="192.168.0.1"
    [CR1]="192.168.0.2"
    [CR2]="192.168.0.3"
    [CR3]="192.168.0.4"
    [LER_Egress]="192.168.0.5"
)
declare -A MPLS_IFACES=(
    [LER_Ingress]="leri-tx1 leri-tx2 leri-tx3 leri-cr1 leri-cr2 leri-cr3"
    [CR1]="cr1-leri cr1-lere"
    [CR2]="cr2-leri cr2-lere"
    [CR3]="cr3-leri cr3-lere"
    [LER_Egress]="lere-cr1 lere-cr2 lere-cr3 lere-rx1 lere-rx2 lere-rx3"
)
for cname in LER_Ingress CR1 CR2 CR3 LER_Egress; do
    lo="${LO_IP[$cname]}"
    nse "$cname" ip addr add "${lo}/32" dev lo
    nse "$cname" ip link set lo up
    nse "$cname" sysctl -qw net.ipv4.ip_forward=1
    nse "$cname" sysctl -qw net.mpls.platform_labels=65536
    for iface in ${MPLS_IFACES[$cname]}; do
        nse "$cname" sysctl -qw "net.mpls.conf.${iface}.input=1" 2>/dev/null || true
    done
    echo "  [ok] $cname (lo=${lo}/32)"
done

# ── 6. Tx/Rxルーティング ──────────────────────────────────────────────
echo ""
echo "=== [6] Tx/Rxルーティング ==="
nse Tx1 ip route add default via 10.10.1.2 dev tx1-leri
nse Tx2 ip route add default via 10.10.2.2 dev tx2-leri
nse Tx3 ip route add default via 10.10.3.2 dev tx3-leri
nse Rx1 ip route add default via 10.20.1.2 dev rx1-lere
nse Rx2 ip route add default via 10.20.2.2 dev rx2-lere
nse Rx3 ip route add default via 10.20.3.2 dev rx3-lere
echo "  [ok]"

# ── 7. FRR companionコンテナ起動 ──────────────────────────────────────
echo ""
echo "=== [7] FRR companionコンテナ起動 ==="

start_frr() {
    local main=$1 router_id=$2 lo_ip=$3 sid_index=$4
    shift 4
    local ospf_ifaces=("$@")
    local cfg_dir="/tmp/frr-lab-${main}"
    mkdir -p "$cfg_dir"
    chmod 777 "$cfg_dir"

    # daemons ファイル
    cat > "${cfg_dir}/daemons" << 'DAEMONS'
zebra=yes
ospfd=yes
bfdd=yes
staticd=yes
vtysh_enable=yes
DAEMONS

    echo "service integrated-vtysh-config" > "${cfg_dir}/vtysh.conf"

    # frr.conf: OSPF-SR + BFD
    {
        cat << HEADER
frr version 8.4
frr defaults traditional
hostname frr-${main}
log syslog informational
!
HEADER
        # インタフェース設定 (OSPF p2p + BFD)
        for iface in "${ospf_ifaces[@]}"; do
            echo "interface ${iface}"
            echo " ip ospf network point-to-point"
            echo " ip ospf hello-interval 1"
            echo " ip ospf dead-interval 3"
            echo " ip ospf bfd"
            if [ "$main" = "LER_Ingress" ] && [ "$iface" != "leri-cr1" ]; then
                echo " ip ospf cost 1000"
            fi
            echo "!"
        done
        # BFDプロファイル
        cat << BFD
bfd
 profile fast
  receive-interval 50
  transmit-interval 50
  detect-multiplier 3
 !
!
BFD
        # OSPF + Segment Routing
        # leri-cr2/cr3にcost 1000を設定済みのため、全経路がCR1経由に集約される
        cat << OSPF
router ospf
 ospf router-id ${router_id}
 network 10.0.0.0/8 area 0
 network 10.10.0.0/16 area 0
 network 10.20.0.0/16 area 0
 network 192.168.0.0/24 area 0
 capability opaque
 mpls-te on
 mpls-te router-address ${lo_ip}
 segment-routing on
 segment-routing global-block 16000 23999
 segment-routing node-msd 8
 segment-routing prefix ${lo_ip}/32 index ${sid_index} no-php-flag
!
OSPF
    } > "${cfg_dir}/frr.conf"
    chmod 644 "${cfg_dir}"/*

    docker rm -f "frr-${main}" 2>/dev/null || true
    docker run -d --name "frr-${main}" \
        --network "container:${main}" \
        --privileged \
        -v "${cfg_dir}:/etc/frr" \
        "$FRR_IMAGE"
    echo "  [ok] frr-${main} (router-id=${router_id}, SID=${sid_index}, label=$((16000 + sid_index)))"
}

# ospf_ifaces: OSPFを有効にするインタフェース (lo は自動)
start_frr LER_Ingress 192.168.0.1 192.168.0.1 1 \
    leri-cr1 leri-cr2 leri-cr3

start_frr CR1 192.168.0.2 192.168.0.2 2 \
    cr1-leri cr1-lere

start_frr CR2 192.168.0.3 192.168.0.3 3 \
    cr2-leri cr2-lere

start_frr CR3 192.168.0.4 192.168.0.4 4 \
    cr3-leri cr3-lere

start_frr LER_Egress 192.168.0.5 192.168.0.5 5 \
    lere-cr1 lere-cr2 lere-cr3

echo ""
echo "=== [8] OSPF収束待ち (35秒) ==="
sleep 35

echo ""
echo "=== OSPF/BFD 状態確認 ==="
echo "--- OSPF neighbors (LER_Ingress) ---"
docker exec frr-LER_Ingress vtysh -c "show ip ospf neighbor" 2>/dev/null || echo "  (収束中)"
echo ""
echo "--- SR ラベルテーブル (LER_Ingress) ---"
docker exec frr-LER_Ingress vtysh -c "show mpls table" 2>/dev/null || echo "  (準備中)"

echo ""
echo "=== セットアップ完了 ==="
echo "次のステップ:"
echo "  sudo bash scripts/frr_dscp_te.sh   # DSCP + SR TE + TC/HTB"
echo "  sudo bash scripts/frr_te_monitor.sh &  # 動的TE経路モニター"
