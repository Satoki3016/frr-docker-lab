#!/bin/bash
# SR-MPLS Fix 2: SR on/off トグル → ospfd 再起動 (SW1)
# physical2_sr_fix_sw1.sh 実行後も Node SID が出ない場合に実行
# 実行: SW1上で  sudo bash scripts/physical2_sr_fix2_sw1.sh
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
SEP="════════════════════════════════════════════"

# ── MPLS interface input フラグ (awk の @ifN 除去版) ─────────────
echo "$SEP"
echo "【Fix A】MPLS インタフェース input 有効化"
for ctr in LER_Ingress CR1 CR2 CR3; do
    PID=$(docker inspect --format '{{.State.Pid}}' "$ctr" 2>/dev/null || true)
    [ -z "$PID" ] && continue
    echo "  $ctr (PID=$PID):"
    # @ifN サフィックスを切り捨ててからsysctl
    while IFS= read -r iface; do
        iface="${iface%%@*}"
        [[ -z "$iface" ]] && continue
        nsenter -t "$PID" -n -- sysctl -w "net.mpls.conf.${iface}.input=1" 2>/dev/null \
            && echo "    ${iface}: input=1" || true
    done < <(nsenter -t "$PID" -n -- ip -o link show | awk -F': ' '{print $2}')
done
echo ""

# ── Step 1: OSPF 状態確認 ────────────────────────────────────────
echo "$SEP"
echo "【Step 1】現在の OSPF 状態確認"
echo ""
echo "--- show ip ospf (LER_Ingress) ---"
docker exec frr-LER_Ingress vtysh -c "show ip ospf" 2>/dev/null | \
    grep -E "Opaque|opaque|segment|TE|SRGB|SR|router.id|area|Area" | head -20 || true

echo ""
echo "--- show ip ospf database ---"
docker exec frr-LER_Ingress vtysh -c "show ip ospf database" 2>/dev/null | head -40 || true

echo ""

# ── Step 2: segment-routing on を off→on でトグル ───────────────
echo "$SEP"
echo "【Step 2】segment-routing on をトグル (SR モジュール再初期化)"
echo ""
for name in LER_Ingress CR1 CR2 CR3; do
    lo="${LO_IP[$name]}"
    idx="${SR_INDEX[$name]}"
    echo "  frr-${name}: no segment-routing on → segment-routing on"
    {
        echo "configure terminal"
        echo "router ospf"
        echo " no segment-routing on"
        echo "exit"
        echo "end"
    } | docker exec -i "frr-${name}" vtysh > /dev/null 2>&1
    sleep 1
    {
        echo "configure terminal"
        echo "router ospf"
        echo " segment-routing on"
        echo " segment-routing global-block ${SRGB_LOW} ${SRGB_HIGH}"
        echo " segment-routing node-msd 8"
        echo " segment-routing prefix ${lo}/32 index ${idx}"
        echo "exit"
        echo "end"
        echo "write memory"
    } | docker exec -i "frr-${name}" vtysh > /dev/null 2>&1
    echo "  [ok] frr-${name}"
done
echo ""
echo "収束待ち (20秒) ..."
sleep 20

echo ""
echo "--- Opaque LSA 確認 (トグル後) ---"
docker exec frr-LER_Ingress vtysh -c "show ip ospf database opaque-area" 2>/dev/null | head -30 || true
echo ""
echo "--- MPLS テーブル (トグル後) ---"
docker exec frr-LER_Ingress vtysh -c "show mpls table" 2>/dev/null | grep -E "1600[0-9]" | head -10 || \
    echo "  → Node SID (16001-16004) はまだ出ていない"

# Node SID が出たか確認
if docker exec frr-LER_Ingress vtysh -c "show mpls table" 2>/dev/null | grep -q "16001"; then
    echo ""
    echo "✓ Node SID 16001 確認！トグルで解決しました。"
    echo ""
    docker exec frr-LER_Ingress vtysh -c "show mpls table" 2>/dev/null
    exit 0
fi

echo ""

# ── Step 3: ospfd 再起動 ─────────────────────────────────────────
echo "$SEP"
echo "【Step 3】ospfd 再起動 (SIGTERM → watchfrr が自動再起動)"
echo "  注意: OSPF 隣接が一時的に切断されます (30-60秒で復旧)"
echo ""
for name in LER_Ingress CR1 CR2 CR3; do
    echo "  frr-${name}: ospfd に SIGTERM を送信"
    docker exec "frr-${name}" sh -c \
        'pid=$(cat /var/run/frr/ospfd.pid 2>/dev/null || pgrep ospfd); [ -n "$pid" ] && kill -TERM $pid' \
        2>/dev/null || docker exec "frr-${name}" pkill -TERM ospfd 2>/dev/null || true
    sleep 2
done

echo ""
echo "ospfd 再起動・OSPF 再収束待ち (45秒) ..."
sleep 45

echo ""
echo "--- OSPF neighbor 確認 ---"
docker exec frr-LER_Ingress vtysh -c "show ip ospf neighbor" 2>/dev/null | head -10 || true

echo ""
echo "--- Opaque LSA 確認 (ospfd 再起動後) ---"
docker exec frr-LER_Ingress vtysh -c "show ip ospf database opaque-area" 2>/dev/null | head -50 || true

echo ""
echo "--- MPLS テーブル全件 (ospfd 再起動後) ---"
docker exec frr-LER_Ingress vtysh -c "show mpls table" 2>/dev/null || true

echo ""
echo "$SEP"
echo "■ 確認完了"
echo ""
echo "Node SID 16001-16004 が MPLS テーブルに出ていれば成功"
echo "引き続き出ない場合:"
echo "  → sudo bash ~/scripts/physical2_sr_fix2_sw2.sh  (SW2の ospfd 再起動)"
echo "  → docker exec frr-LER_Ingress vtysh -c 'show ip ospf database'"
echo "     で Opaque-LSA エントリが増えているか確認"
