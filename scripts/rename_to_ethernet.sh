#!/bin/bash
# 論理名 → 元のEthernetX名に戻す
set -e

rename_if() {
    local old=$1 new=$2
    if ip link show "$old" &>/dev/null; then
        ip link set "$old" down 2>/dev/null || true
        ip link set "$old" name "$new"
        ip link set "$new" up
        echo "  [ok] $old → $new"
    fi
}

echo "=== インターフェース名をEthernetXに戻す ==="
rename_if tx1-ler   Ethernet0
rename_if leri-tx1  Ethernet1
rename_if tx2-ler   Ethernet2
rename_if leri-tx2  Ethernet3
rename_if tx3-ler   Ethernet4
rename_if leri-tx3  Ethernet5
rename_if leri-cr1  Ethernet6
rename_if cr1-leri  Ethernet7
rename_if leri-cr2  Ethernet8
rename_if cr2-leri  Ethernet9
rename_if leri-cr3  Ethernet10
rename_if cr3-leri  Ethernet11
rename_if cr1-lere  Ethernet12
rename_if lere-cr1  Ethernet13
rename_if cr2-lere  Ethernet14
rename_if lere-cr2  Ethernet15
rename_if cr3-lere  Ethernet16
rename_if lere-cr3  Ethernet17
rename_if lere-rx1  Ethernet18
rename_if rx1-lere  Ethernet19
rename_if lere-rx2  Ethernet20
rename_if rx2-lere  Ethernet21
rename_if lere-rx3  Ethernet22
rename_if rx3-lere  Ethernet23

echo ""
echo "=== 確認 ==="
ip link show | grep -E "Ethernet[0-9]" | awk '{print $2, $9}' | tr -d ':'
