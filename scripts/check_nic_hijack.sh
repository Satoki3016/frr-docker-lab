#!/bin/bash
# 実験用NICを奪う macvtap / VM を検出する。
#
# libvirt の macvtap が実験用10G NICに付くと「送信は通るが受信だけ奪われる」。
# エラーは出ず OSPF隣接も張れるため、経路別の到達性で初めて気づく。
# 2026-09-18 に2度目の再発。原因VMは ubuntu2004virt1 (net1 = 52:54:00:20:bf:12)。
RISKY_VMS="ubuntu2004virt1 ubuntu2004virt2 ubuntu2004virt3 ubuntu2004virt34 ubuntu2004virt234"
rc=0

echo "=== macvtap / macvlan ==="
found=$(ip -o link show 2>/dev/null | grep -iE "macvtap|macvlan" || true)
if [ -n "$found" ]; then
    echo "$found" | sed -E 's/^([0-9]+): ([^@:]+).*link\/ether ([0-9a-f:]+).*/  \2  MAC=\3/'
    echo "  [NG] 実験用NICの受信を奪っています。削除してください:"
    echo "$found" | sed -E 's/^[0-9]+: ([^@:]+).*/         sudo ip link del \1/'
    rc=1
else
    echo "  [OK] なし"
fi

echo "=== 実験用NICを奪う構成のVM ==="
hit=0
for vm in $RISKY_VMS; do
    pid=$(pgrep -f "qemu-system.*guest=$vm[,.]" 2>/dev/null | head -1)
    [ -z "$pid" ] && pid=$(pgrep -f "qemu-system.*$vm" 2>/dev/null | head -1)
    if [ -n "$pid" ]; then
        echo "  [NG] $vm が稼働中 (PID $pid)"
        echo "         sudo virsh shutdown $vm"
        hit=1; rc=1
    fi
done
[ "$hit" -eq 0 ] && echo "  [OK] 該当VMなし"

echo "=== その他の稼働VM (参考) ==="
all_vms=$(pgrep -a qemu-system 2>/dev/null \
    | grep -oE 'guest=[^, ]+' | cut -d= -f2 | sort -u || true)
other=""
for vm in $all_vms; do
    case " $RISKY_VMS " in *" $vm "*) ;; *) other="$other  $vm" ;; esac
done
if [ -n "$other" ]; then printf '%s\n' $other | sed 's/^/  /'; else echo "  (なし)"; fi

exit $rc
