#!/usr/bin/env python3
"""無線チェーンのボトルネックを切り分ける (v2)。

v1 では /sys/class/net/*/speed が空を返したため判定できなかった。
ODU は eth0 (CPU ポート) + eth0p0..p7 (内蔵スイッチポート) という構成なので、
どのポートが実際にトラフィックを運んでいるかをバイトカウンタで特定し、
そのポートの速度を複数の手段で読む。エラーは握りつぶさず表示する。
"""
from __future__ import annotations
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from radwin_ssh import ssh_run  # noqa: E402

ODUS = [("無線1 AP", "192.168.1.31"), ("無線2 AP", "192.168.1.33")]

# 1) 全 netdev の速度を「読めなかった理由つき」で出す
SPEED = r"""
for d in /sys/class/net/*/; do
  n=`basename $d`
  case $n in lo|gre*|erspan*|ip6*|sit*|tunl*) continue;; esac
  st=`cat $d/operstate 2>/dev/null || echo ?`
  ca=`cat $d/carrier 2>/dev/null || echo ?`
  sp=`cat $d/speed 2>/dev/null` ; [ -z "$sp" ] && sp="(speed読めず)"
  rx=`cat $d/statistics/rx_bytes 2>/dev/null || echo 0`
  tx=`cat $d/statistics/tx_bytes 2>/dev/null || echo 0`
  echo "$n|$st|$ca|$sp|$rx|$tx"
done
"""

EXTRA = [
    ("ethtool の有無", "command -v ethtool || echo '(ethtool なし)'"),
    ("eth0 の詳細", "ethtool eth0 2>&1 | head -12"),
    ("debugfs (wil6210)",
     "ls /sys/kernel/debug/ieee80211/phy0/wil6210/ 2>&1 | head -30"),
]


def snap(ip):
    code, out = ssh_run(ip, SPEED, timeout=25.0)
    d = {}
    for line in (out or "").splitlines():
        f = line.strip().split("|")
        if len(f) == 6:
            d[f[0]] = {"state": f[1], "carrier": f[2], "speed": f[3],
                       "rx": int(f[4]), "tx": int(f[5])}
    return d


def main() -> int:
    print("=" * 72)
    print("ボトルネック切り分け v2 — 稼働ポートの特定と速度読み取り")
    print("=" * 72)
    for label, ip in ODUS:
        print(f"\n■ {label}  ({ip})")
        a = snap(ip)
        if not a:
            print("   [取得失敗]"); continue
        time.sleep(5.0)
        b = snap(ip)

        print(f"   {'port':10s} {'state':8s} {'car':4s} {'speed':14s} "
              f"{'5秒間の RX':>12s} {'5秒間の TX':>12s}")
        for n in sorted(a):
            if n not in b: continue
            drx = (b[n]['rx'] - a[n]['rx']) * 8 / 5 / 1e6
            dtx = (b[n]['tx'] - a[n]['tx']) * 8 / 5 / 1e6
            mark = "  <<<" if max(drx, dtx) > 50 else ""
            print(f"   {n:10s} {a[n]['state']:8s} {a[n]['carrier']:4s} "
                  f"{a[n]['speed']:14s} {drx:9.1f}Mbps {dtx:9.1f}Mbps{mark}")

        for name, cmd in EXTRA:
            code, out = ssh_run(ip, cmd + " 2>&1", timeout=20.0)
            out = (out or "").strip()
            print(f"   -- {name}:")
            for l in [l for l in out.splitlines() if l.strip()][:14]:
                print(f"        {l}")
    print("\n" + "=" * 72)
    print("見方: '<<<' が付いた行が実際にトラフィックを運んでいるポート。")
    print("      そのポートの speed が 2500 なら Ethernet 律速、")
    print("      空欄/10000 以上なら無線 (TDD) 律速。")
    print("      ※ トラフィックを流しながら実行すること。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
