#!/bin/bash
# C2で使う6ポート全NICのnetdev登録状態を確認し、消えていればPCI unbind/bindで復旧する。
# 原因: 度重なるip netns作成・削除の繰り返しで、多機能NIC(2ポートカード)の
# netdevが片方または両方消失することがある(2026-07-21確認、複数ドライバで再現)。
# 使い方: sudo bash scripts/fix_nic_netdev.sh
set -e

declare -A PCI_MAP=(
  [enp5s0f0]="0000:05:00.0"
  [enp5s0f1]="0000:05:00.1"
  [enp23s0f0np0]="0000:17:00.0"
  [enp23s0f1np1]="0000:17:00.1"
  [enp179s0f0np0]="0000:b3:00.0"
  [enp179s0f1np1]="0000:b3:00.1"
)

echo "=== 現状確認 ==="
broken=()
for nic in "${!PCI_MAP[@]}"; do
    pci="${PCI_MAP[$nic]}"
    found=$(ls "/sys/bus/pci/devices/$pci/net/" 2>/dev/null)
    if [ -z "$found" ]; then
        echo "  [NG] $nic ($pci) — netdev消失"
        broken+=("$pci")
    else
        echo "  [ok] $nic ($pci) — $found"
    fi
done

if [ ${#broken[@]} -eq 0 ]; then
    echo ""
    echo "=== 全6ポート正常。修復不要 ==="
    exit 0
fi

echo ""
echo "=== ${#broken[@]}件を修復 (PCI unbind/bind) ==="
for pci in "${broken[@]}"; do
    drv=$(basename "$(readlink "/sys/bus/pci/devices/$pci/driver")")
    echo "  $pci (driver: $drv) を再初期化..."
    echo "$pci" > "/sys/bus/pci/drivers/$drv/unbind"
    sleep 2
    echo "$pci" > "/sys/bus/pci/drivers/$drv/bind"
    sleep 3
done

echo ""
echo "=== 修復後の確認 ==="
for nic in "${!PCI_MAP[@]}"; do
    pci="${PCI_MAP[$nic]}"
    found=$(ls "/sys/bus/pci/devices/$pci/net/" 2>/dev/null)
    echo "  $nic ($pci): ${found:-[まだNG]}"
done
