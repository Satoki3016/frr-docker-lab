#!/usr/bin/env python3
"""ODU 内蔵の prs-link-estimator でリンク容量を推定する。

自作の推定式 (PHY × 0.52) は1点の実測から逆算した係数であり根拠が弱い。
メーカーが用意した推定ツールの値と突き合わせて妥当性を確かめる。

  usage: prs-link-estimator [-j] [-i <netdev>] [-a <addr>] [-c <num>] [-s <bytes>] [-t <time>]
  -a はリンクが idle のとき ping flood を流して測る
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from radwin_ssh import ssh_run  # noqa: E402

# (ラベル, 実行するAP, ping flood の相手=STA, 現在のMCSでのPHY)
HOPS = [("無線1", "192.168.1.31", "192.168.1.32"),
        ("無線2", "192.168.1.33", "192.168.1.34")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--time", type=int, default=10, help="測定秒数")
    ap.add_argument("--size", type=int, default=1400, help="ping flood のサイズ")
    a = ap.parse_args()

    print("=" * 70)
    print(f"prs-link-estimator によるリンク容量推定 ({a.time} 秒)")
    print("=" * 70)

    for label, apip, staip in HOPS:
        print(f"\n■ {label}  (AP {apip} → STA {staip})")

        # 現在の MCS を先に記録する。推定値と対応づけるため。
        _, st = ssh_run(apip, "iw dev wlan0 station dump 2>/dev/null "
                              "| grep -E 'tx bitrate|signal:'", timeout=20.0)
        for l in (st or "").splitlines():
            print(f"    {l.strip()}")

        cmd = (f"prs-link-estimator -i wlan0 -a {staip} "
               f"-t {a.time} -s {a.size} -j 2>&1")
        print(f"    $ {cmd}")
        code, out = ssh_run(apip, cmd, timeout=a.time + 25.0)
        out = (out or "").strip()
        if not out:
            print("    (出力なし)")
            continue
        for l in out.splitlines()[:25]:
            print(f"      {l}")

    print("\n" + "=" * 70)
    print("比較の観点:")
    print("  自作の推定式は PHY × 0.52。MCS12 なら 2402 Mbps")
    print("  メーカーの推定値がこれと大きく違えば、0.52 は見直しが必要")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
