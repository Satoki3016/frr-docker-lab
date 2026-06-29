#!/bin/bash
# Phase 3: TI-LFA（Topology-Independent LFA）セットアップ (SW1)
# 前提: physical2_sr_sw1.sh が実行済みであること
# 実行: SW1上で  sudo bash scripts/physical2_tilfa_sw1.sh
#
# TI-LFA: SR-MPLSのトポロジー計算によりリンク障害時の迂回路を事前計算
# BFD検出(150ms) + 即時切替 → フェイルオーバー要件 <150ms を達成
set -e

declare -A LO_IP=(
    [LER_Ingress]="10.255.1.1"
    [CR1]="10.255.1.2"
    [CR2]="10.255.1.3"
    [CR3]="10.255.1.4"
)

enable_tilfa() {
    local name=$1
    echo "  TI-LFA設定: frr-${name}"
    {
        echo "configure terminal"
        echo "router ospf"
        echo " fast-reroute enable lfib-cspf"
        echo "exit"
        echo "end"
        echo "write memory"
    } | docker exec -i "frr-${name}" vtysh
    echo "  [ok] frr-${name}"
}

echo "=== [SW1] TI-LFA 有効化 ==="
for name in LER_Ingress CR1 CR2 CR3; do
    enable_tilfa "$name"
done

# ── 収束待ち ────────────────────────────────────────────────────
echo ""
echo "=== [SW1] TI-LFA SPF収束待ち (10秒) ==="
sleep 10

# ── 状態確認 ─────────────────────────────────────────────────────
echo ""
echo "=== [SW1] TI-LFA状態確認 ==="

echo "--- LFA/TI-LFA バックアップパス (LER_Ingress) ---"
docker exec frr-LER_Ingress vtysh -c "show ip ospf route" 2>/dev/null | \
    grep -E "10\.255\.|10\.20\.|backup|repair" | head -30 || true

echo ""
echo "--- MPLSテーブル (LER_Ingress) ---"
docker exec frr-LER_Ingress vtysh -c "show mpls table" 2>/dev/null | head -40

echo ""
echo "--- running-config SR確認 ---"
docker exec frr-LER_Ingress vtysh -c "show running-config" 2>/dev/null | \
    grep -E "segment-routing|fast-reroute" | head -10 || true

echo ""
echo "=== [SW1] 完了 ==="
cat << 'USAGE'

■ SW2でも実行: sudo bash ~/scripts/physical2_tilfa_sw2.sh

■ フェイルオーバーテスト:
  sudo bash ~/scripts/physical2_tilfa_test.sh

■ TI-LFA動作の確認:
  docker exec frr-LER_Ingress vtysh -c "show ip ospf route"
  → バックアップルートが "backup via ..." で表示されれば TI-LFA 有効
USAGE
