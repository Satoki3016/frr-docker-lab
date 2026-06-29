#!/bin/bash
# SR-MPLS Node SID 修正スクリプト (SW1)
# 診断: physical2_sr_diag.sh を先に実行し出力を確認してから実施
# 実行: SW1上で  sudo bash scripts/physical2_sr_fix_sw1.sh
set -e

declare -A LO_IP=(
    [LER_Ingress]="10.255.1.1"
    [CR1]="10.255.1.2"
    [CR2]="10.255.1.3"
    [CR3]="10.255.1.4"
)
declare -A SR_INDEX=(
    [LER_Ingress]=1
    [CR1]=2
    [CR2]=3
    [CR3]=4
)
SRGB_LOW=16000
SRGB_HIGH=23999
NODE_MSD=8

SEP="════════════════════════════════════════════"

# ── Fix 1: ホストカーネル MPLS 有効化 ────────────────────────────
echo "$SEP"
echo "【Fix 1】ホストカーネル MPLS 設定"

PLAT=$(cat /proc/sys/net/mpls/platform_labels 2>/dev/null || echo "0")
echo "  現在の platform_labels: $PLAT"
if [ "$PLAT" -eq 0 ] 2>/dev/null; then
    echo "  → MPLS 無効。有効化します。"
    sysctl -w net.mpls.platform_labels=1048575
else
    echo "  → MPLS 有効 (platform_labels=$PLAT)"
fi

# コンテナが共有する netns のインタフェースに MPLS input を設定
# (FRR コンテナは --network container:LER_Ingress 等でネットワークを共有)
for ctr in LER_Ingress CR1 CR2 CR3; do
    PID=$(docker inspect --format '{{.State.Pid}}' "$ctr" 2>/dev/null || echo "")
    [ -z "$PID" ] && continue
    echo "  コンテナ $ctr (PID=$PID) の MPLS input 設定:"
    for iface in $(nsenter -t "$PID" -n -- ip -o link show | awk -F': ' '{print $2}' | grep -v lo); do
        nsenter -t "$PID" -n -- sysctl -w "net.mpls.conf.${iface}.input=1" 2>/dev/null || true
    done
    # loopback も有効化
    nsenter -t "$PID" -n -- sysctl -w "net.mpls.conf.lo.input=1" 2>/dev/null || true
    echo "    [ok]"
done

echo ""

# ── Fix 2: OSPF mpls-te + segment-routing 再設定 ──────────────────
echo "$SEP"
echo "【Fix 2】OSPF mpls-te on + SR prefix SID 再設定"
echo ""
echo "注意: FRR 8.x では segment-routing が mpls-te 拡張に依存する場合がある"
echo ""

configure_sr_with_te() {
    local name=$1
    local lo="${LO_IP[$name]}"
    local idx="${SR_INDEX[$name]}"
    local sid=$((SRGB_LOW + idx))
    echo "  設定: frr-${name}  lo=${lo}  index=${idx}  SID=${sid}"
    {
        echo "configure terminal"
        echo "router ospf"
        echo " mpls-te on"
        echo " mpls-te router-address ${lo}"
        echo " segment-routing on"
        echo " segment-routing global-block ${SRGB_LOW} ${SRGB_HIGH}"
        echo " segment-routing node-msd ${NODE_MSD}"
        echo " segment-routing prefix ${lo}/32 index ${idx}"
        echo "exit"
        echo "end"
        echo "write memory"
    } | docker exec -i "frr-${name}" vtysh
    echo "  [ok] frr-${name}"
}

for name in LER_Ingress CR1 CR2 CR3; do
    configure_sr_with_te "$name"
done

echo ""

# ── Fix 3: LER_Egress (SW2) 側も確認メッセージ ───────────────────
echo "$SEP"
echo "【Fix 3】LER_Egress の SR 状態確認 (SW2 側設定は別途必要)"
docker exec frr-LER_Egress vtysh -c "show running-config" 2>/dev/null | \
    grep -E "segment-routing|mpls-te" | head -10 || true

echo ""

# ── 収束待ち ────────────────────────────────────────────────────
echo "$SEP"
echo "SR 収束待ち (20秒) ..."
sleep 20

echo ""

# ── 結果確認 ─────────────────────────────────────────────────────
echo "$SEP"
echo "【結果確認】"

echo ""
echo "--- running-config SR 確認 (LER_Ingress) ---"
docker exec frr-LER_Ingress vtysh -c "show running-config" 2>/dev/null | \
    grep -E "segment-routing|mpls-te|router-info" | head -15 || true

echo ""
echo "--- OSPF Opaque-Area LSA (Extended Prefix SID) ---"
docker exec frr-LER_Ingress vtysh -c "show ip ospf database opaque-area" 2>/dev/null | head -80 || true

echo ""
echo "--- MPLS テーブル (LER_Ingress) ---"
docker exec frr-LER_Ingress vtysh -c "show mpls table" 2>/dev/null || true

echo ""
echo "--- MPLS テーブル (CR1) ---"
docker exec frr-CR1 vtysh -c "show mpls table" 2>/dev/null || true

echo ""
echo "$SEP"
echo "■ 修正完了"
echo ""
echo "判定:"
echo "  Node SID 16001-16004 が LER_Ingress の MPLS テーブルに出れば成功"
echo "  出ない場合 → 診断スクリプト出力を確認"
echo "    sudo bash scripts/physical2_sr_diag.sh"
echo ""
echo "SW2 側 (LER_Egress SID=16005) も修正が必要な場合:"
echo "  sudo bash ~/scripts/physical2_sr_fix_sw2.sh"
