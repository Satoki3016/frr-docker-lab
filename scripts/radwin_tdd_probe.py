#!/usr/bin/env python3
"""ODU が TDD の時間割り当てを設定できるかを調べる。

802.11ad ではデータ転送期間 (DTI) を送信用と受信用に割り振る。規格上は
非対称な割り当てが可能だが、通常はファームウェア内部で決まり外部から
触れない。ドライバが設定項目として露出しているかを確認する。
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from radwin_ssh import ssh_run  # noqa: E402

ODUS = [("無線1 AP", "192.168.1.31"), ("無線2 AP", "192.168.1.33")]

PROBES = [
    ("① 実際の無線ドライバ (USB階層を遡る)",
     "readlink -f /sys/class/net/wlan0/device/driver 2>/dev/null; "
     "for m in $(lsmod 2>/dev/null | awk 'NR>1{print $1}'); do "
     "  case $m in *wil*|*60g*|*wl*|*mmw*|*ath*|*qca*) echo \"module: $m\";; esac; done"),
    ("② debugfs の全項目 (絞り込みなし)",
     "ls /sys/kernel/debug/ieee80211/phy0/ 2>/dev/null | tr '\\n' ' '; echo; "
     "ls -d /sys/kernel/debug/ieee80211/phy0/*/ 2>/dev/null"),
    ("③ debugfs をより深く探索",
     "find /sys/kernel/debug/ieee80211 -maxdepth 5 -type f 2>/dev/null | head -40"),
    ("④ 無線モジュールのパラメータ",
     "for m in $(lsmod 2>/dev/null | awk 'NR>1{print $1}'); do "
     "  if [ -d /sys/module/$m/parameters ]; then "
     "    n=$(ls /sys/module/$m/parameters | wc -l); "
     "    [ $n -gt 0 ] && echo \"$m: $(ls /sys/module/$m/parameters | tr '\\n' ' ')\"; "
     "  fi; done | head -20"),
    ("⑤ iw phy0 info の全体 (先頭60行)",
     "iw phy0 info 2>&1 | head -60"),
    ("⑥ wlan0 に設定できる項目",
     "iw dev wlan0 get power_save 2>&1; iw dev wlan0 info 2>&1 | head -20"),
    ("⑦ ベンダ独自のコマンド・設定 (広く探す)",
     "ls /usr/sbin /usr/bin /sbin /bin 2>/dev/null | sort -u | "
     "grep -ivE '^(ls|cat|cp|mv|rm|sh|ps|ip|tc|awk|sed|grep)$' | "
     "grep -iE 'rad|wil|60|mmw|terra|wlan|wifi|link|cfg|conf' | head -20"),
]

def main() -> int:
    print("=" * 72)
    print("TDD 時間割り当ての設定可否を調べる")
    print("=" * 72)
    for label, ip in ODUS:
        print(f"\n■ {label}  ({ip})")
        for name, cmd in PROBES:
            code, out = ssh_run(ip, cmd + " 2>&1", timeout=25.0)
            out = (out or "").strip()
            print(f"  {name}:")
            if not out:
                print("      (出力なし)")
                continue
            for line in [l for l in out.splitlines() if l.strip()][:12]:
                print(f"      {line}")
    print("\n" + "=" * 72)
    print("判定の目安:")
    print("  ③や④に tdd / sched / alloc を含む項目があれば、設定できる可能性あり")
    print("  ⑥にベンダCLIがあれば、そこから設定できる可能性あり")
    print("  いずれも無ければ、ファームウェア内部で固定。外部からは変更不可")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
