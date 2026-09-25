#!/usr/bin/env python3
"""prs_falcon の主要パラメータと、ベンダCLIの使い方を調べる。

狙いは「再現可能な容量制御」の手段を確定すること。
アンテナを手で動かす代わりに、MCS 上限や送信電力を指定できれば
同じ条件を何度でも再現できる。

権限が 0644 なら実行中に変更でき、0444 ならモジュール読み込み時のみ。
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from radwin_ssh import ssh_run  # noqa: E402

ODUS = [("無線1 AP", "192.168.1.31")]      # まず1台で確認する

KEY_PARAMS = [
    "PRS_MAX_MCS", "PRS_TX_OUTPUT_POWER", "PrsTxSchedulerType",
    "PRS_BEACON_INTERVAL_TU", "PRS_MAX_AMSDU_SIZE_BYTES", "PRS_AMSDU_TYPE",
    "PrsLinkStatusMcsUpdateMode", "PRS_DEVICE_MODE", "PrsDriverOperationalMode",
]

PROBES = [
    ("① UCI 設定 /etc/config/peraso",
     "cat /etc/config/peraso 2>&1 | head -60"),
    ("② uci コマンドで参照",
     "uci show peraso 2>&1 | head -40"),
    ("③ MCS / 電力に関係する設定項目",
     "cat /etc/config/peraso 2>/dev/null | grep -inE 'mcs|power|txpwr|rate|sched|tdd' ; "
     "uci show peraso 2>/dev/null | grep -inE 'mcs|power|txpwr|rate|sched|tdd'"),
    ("④ raconfig のサブコマンド探索",
     "for a in '' '-h' '--help' 'show' 'get' 'status'; do "
     "  echo \"--- raconfig $a\"; raconfig $a 2>&1 | head -8; done"),
    ("⑤ 現在の MCS (書き込み試験の前後で比較する基準値)",
     "iw dev wlan0 station dump 2>/dev/null | grep -E 'tx bitrate|signal'"),
]

def main() -> int:
    print("=" * 74)
    print("prs_falcon パラメータとベンダCLIの調査")
    print("=" * 74)
    for label, ip in ODUS:
        print(f"\n■ {label}  ({ip})")
        for name, cmd in PROBES:
            code, out = ssh_run(ip, cmd + " 2>&1", timeout=30.0)
            out = (out or "").strip()
            print(f"\n  {name}:")
            for line in [l for l in out.splitlines() if l.strip()][:28]:
                print(f"      {line}")
            if not out:
                print("      (出力なし)")
    print("\n" + "=" * 74)
    print("見方:")
    print("  権限 644 → 実行中に変更できる。障害注入に直接使える")
    print("  権限 444 → 読み取り専用。モジュール読み込み時のみ指定可能")
    print("  ③にオプションがあれば、ベンダCLI経由で設定できる可能性")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
