#!/bin/bash
# virttrx Tx/Rx namespace セットアップ（SONiC分離アーキテクチャ用）
#
# SONiC スイッチがルーター機能（LER_Ingress/CoreRouter/LER_Egress）を担うため、
# virttrx は送受信ホスト（Tx/Rx）のみを担当する。
#
# 物理NIC割り当て（virttrx ↔ SONiC 光ファイバー接続）:
#   enp23s0f0np0  → Tx1_ns (10.10.1.2/30)  ↔ SONiC Ethernet0  (10.10.1.1)
#   enp23s0f1np1  → Tx2_ns (10.10.2.2/30)  ↔ SONiC Ethernet2  (10.10.2.1)
#   enp179s0f0np0 → Tx3_ns (10.10.3.2/30)  ↔ SONiC Ethernet4  (10.10.3.1)
#   enp179s0f1np1 → Rx1_ns (10.20.1.2/30)  ↔ SONiC Ethernet18 (10.20.1.1)
#   enp5s0f0      → Rx2_ns (10.20.2.2/30)  ↔ SONiC Ethernet20 (10.20.2.1)
#   enp5s0f1      → Rx3_ns (10.20.3.2/30)  ↔ SONiC Ethernet22 (10.20.3.1)
#
set -e

NICS="enp23s0f0np0 enp23s0f1np1 enp179s0f0np0 enp179s0f1np1 enp5s0f0 enp5s0f1"

# ── 既存 namespace クリーンアップ ───────────────────────────────
echo "=== 既存 namespace クリーンアップ ==="
for ns in Tx1_ns Tx2_ns Tx3_ns Rx1_ns Rx2_ns Rx3_ns \
          LER_Ingress_ns CoreRouter1_ns CoreRouter2_ns CoreRouter3_ns LER_Egress_ns; do
    if ip netns list 2>/dev/null | awk '{print $1}' | grep -qxF "$ns"; then
        for iface in $(ip netns exec "$ns" ip link show 2>/dev/null \
                       | grep -E "^[0-9]+" | awk -F': ' '{print $2}' | grep -v lo); do
            ip netns exec "$ns" ip link set "$iface" netns 1 2>/dev/null || true
        done
        ip netns del "$ns"
        echo "  [del] $ns"
    fi
done

# macvtap 確認（enp179 が VM に割り当てられている場合）
if ip link show type macvtap 2>/dev/null | grep -q enp179; then
    echo "[WARN] enp179 に macvtap インターフェースが存在します"
    echo "       virsh/KVM の NIC 割り当てを解除してから再実行してください"
    exit 1
fi

# 物理NICをroot nsに戻してIPフラッシュ
for nic in $NICS; do
    ip addr flush dev "$nic" 2>/dev/null || true
    ip link set "$nic" up 2>/dev/null || true
done

# ── namespace 作成 ────────────────────────────────────────────
echo ""
echo "=== namespace 作成 ==="
for ns in Tx1_ns Tx2_ns Tx3_ns Rx1_ns Rx2_ns Rx3_ns; do
    ip netns add "$ns"
    ip netns exec "$ns" ip link set lo up
    echo "  [ok] $ns"
done

# ── 物理NIC割り当て ────────────────────────────────────────────
move_nic() {
    local ns=$1 nic=$2 ip=$3 gw=$4
    ip link set "$nic" down 2>/dev/null || true
    ip link set "$nic" netns "$ns"
    ip netns exec "$ns" ip addr add "$ip" dev "$nic"
    ip netns exec "$ns" ip link set "$nic" up
    ip netns exec "$ns" ip route add default via "$gw" dev "$nic"
    echo "  [ok] $ns: $nic ($ip) gw $gw"
}

echo ""
echo "=== 物理NIC割り当て ==="
move_nic Tx1_ns  enp23s0f0np0  10.10.1.2/30 10.10.1.1
move_nic Tx2_ns  enp23s0f1np1  10.10.2.2/30 10.10.2.1
move_nic Tx3_ns  enp179s0f0np0 10.10.3.2/30 10.10.3.1
move_nic Rx1_ns  enp179s0f1np1 10.20.1.2/30 10.20.1.1
move_nic Rx2_ns  enp5s0f0      10.20.2.2/30 10.20.2.1
move_nic Rx3_ns  enp5s0f1      10.20.3.2/30 10.20.3.1

echo ""
echo "=== 設定完了 ==="
echo "SONiC側の設定後に以下で疎通確認:"
echo "  sudo ip netns exec Tx1_ns ping -c3 10.10.1.1  # SONiC LER_Ingress"
echo "  sudo ip netns exec Tx1_ns ping -c3 10.20.1.2  # Rx1_ns (MPLS経由)"
