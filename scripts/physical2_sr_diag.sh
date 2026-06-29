#!/bin/bash
# SR-MPLS 診断スクリプト - Node SID (16001-16005) が MPLS テーブルに出ない原因調査
# 実行: SW1上で  sudo bash scripts/physical2_sr_diag.sh

SEP="════════════════════════════════════════════"

echo "$SEP"
echo "■ SR-MPLS 診断開始 ($(date))"
echo "$SEP"

# ── 1. カーネル MPLS 設定確認 ─────────────────────────────────────
echo ""
echo "【1】ホストカーネル MPLS 設定"
echo "--- platform_labels (0=MPLS無効) ---"
cat /proc/sys/net/mpls/platform_labels 2>/dev/null || echo "  /proc/sys/net/mpls/platform_labels が存在しない → MPLS無効"

echo "--- インタフェース別 MPLS input フラグ ---"
for iface in lo leri-cr1 leri-cr2 leri-cr3; do
    val=$(cat /proc/sys/net/mpls/conf/${iface}/input 2>/dev/null || echo "なし")
    echo "  ${iface}: input=${val}"
done

# ── 2. FRR バージョン確認 ─────────────────────────────────────────
echo ""
echo "【2】FRR バージョン"
docker exec frr-LER_Ingress vtysh -c "show version" 2>/dev/null | grep -E "FRRouting|Version" | head -3 || true

# ── 3. running-config SR 関連 ────────────────────────────────────
echo ""
echo "【3】running-config (SR 関連) - LER_Ingress"
docker exec frr-LER_Ingress vtysh -c "show running-config" 2>/dev/null | \
    grep -E "segment-routing|fast-reroute|router-info|mpls-te|ospf" | head -30 || true

echo ""
echo "【3b】running-config (SR 関連) - CR1"
docker exec frr-CR1 vtysh -c "show running-config" 2>/dev/null | \
    grep -E "segment-routing|router-info|mpls-te" | head -20 || true

# ── 4. OSPF Router Information LSA ──────────────────────────────
echo ""
echo "【4】OSPF Router Information LSA (SR Capabilities) - LER_Ingress"
docker exec frr-LER_Ingress vtysh -c "show ip ospf database opaque-area" 2>/dev/null | \
    grep -A2 -B2 -E "Router Information|RI LSA|SR Algorithm|SRGB|Segment Routing" | head -40 || true

# ── 5. Extended Prefix LSA (SID 広告) ───────────────────────────
echo ""
echo "【5】Extended Prefix Opaque LSA (全ルータ) - LER_Ingress から見える LSA"
docker exec frr-LER_Ingress vtysh -c "show ip ospf database opaque-area" 2>/dev/null | \
    grep -A5 -B2 -E "Extended Prefix|Prefix-SID|SID Index|type-7" | head -60 || true

echo ""
echo "【5b】自己生成 Opaque LSA"
docker exec frr-LER_Ingress vtysh -c "show ip ospf database opaque-area self-originate" 2>/dev/null | head -60 || true

# ── 6. OSPF database 概要 ────────────────────────────────────────
echo ""
echo "【6】OSPF database summary - LER_Ingress"
docker exec frr-LER_Ingress vtysh -c "show ip ospf database" 2>/dev/null | \
    grep -E "Type-[0-9]|Opaque|Area|Router|Network|Summary" | head -30 || true

# ── 7. MPLS テーブル (全件) ────────────────────────────────────
echo ""
echo "【7】MPLS テーブル全件 - LER_Ingress"
docker exec frr-LER_Ingress vtysh -c "show mpls table" 2>/dev/null || true

echo ""
echo "【7b】MPLS テーブル - CR1"
docker exec frr-CR1 vtysh -c "show mpls table" 2>/dev/null || true

# ── 8. カーネル MPLS テーブル ───────────────────────────────────
echo ""
echo "【8】カーネル MPLS テーブル (LER_Ingress コンテナの netns)"
LER_PID=$(docker inspect --format '{{.State.Pid}}' LER_Ingress 2>/dev/null)
if [ -n "$LER_PID" ]; then
    echo "  LER_Ingress netns PID=$LER_PID"
    nsenter -t "$LER_PID" -n -- ip -M route show 2>/dev/null | head -20 || \
    nsenter -t "$LER_PID" -n -- ip route show table 100 2>/dev/null | head -20 || true
fi

# ── 9. zebra SR 状態 ─────────────────────────────────────────────
echo ""
echo "【9】zebra MPLS state (LER_Ingress)"
docker exec frr-LER_Ingress vtysh -c "show zebra mpls table" 2>/dev/null | head -20 || \
docker exec frr-LER_Ingress vtysh -c "show mpls ftn" 2>/dev/null | head -20 || true

# ── 10. OSPF neighbor と SR 有効性 ─────────────────────────────
echo ""
echo "【10】OSPF neighbor (LER_Ingress)"
docker exec frr-LER_Ingress vtysh -c "show ip ospf neighbor" 2>/dev/null | head -20 || true

echo ""
echo "【10b】OSPF SR 状態 (コマンドが通れば)"
docker exec frr-LER_Ingress vtysh -c "show ip ospf segment-routing" 2>/dev/null || \
docker exec frr-LER_Ingress vtysh -c "show ip ospf te router" 2>/dev/null | head -20 || true

echo ""
echo "$SEP"
echo "■ 診断完了"
echo ""
echo "確認ポイント:"
echo "  【1】platform_labels が 0 → MPLS カーネルモジュール未設定 (根本原因)"
echo "  【4】SRGB が RI LSA に入っていない → segment-routing on が効いていない"
echo "  【5】Extended Prefix LSA が見えない → SID が OSPF 経由で配布されていない"
echo "  【7】16001-16005 が無い → FRR が MPLS テーブルに SR エントリを書いていない"
