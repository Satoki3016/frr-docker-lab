#!/usr/bin/env python3
"""veth での動作確認用に、偽の ODU の状態を作る (実機では使わない)。

radwin_ssh.py は RADWIN_FAKE_ODU_DIR が設定されていると、SSH の代わりに
<フォルダ>/<IP>.txt の内容 (iw station dump の出力) を返す。このスクリプトはそのファイルを書く。

使い方 (どれも 1 行):
    sudo python3 scripts/radwin_fake_odu.py 9       # 4台とも MCS 9 (推定 1301 Mbps → 整形 1171M)
    sudo python3 scripts/radwin_fake_odu.py 3       # 無線2 だけ MCS 3 に下げる (雨で容量が落ちた想定)
    sudo python3 scripts/radwin_fake_odu.py down    # 無線2 の相手の局がいない (無線断の想定)
"""
from __future__ import annotations

import sys
from pathlib import Path

DIR = Path("/tmp/radwin_fake_odu")
# 実機 (V90, 2026-10-02) で読んだ MCS と PHY の組
PHY = {1: 385.0, 2: 770.0, 3: 962.5, 8: 2310.0, 9: 2502.5, 10: 3080.0, 11: 3850.0, 12: 4620.0}
DUMP = """Station {peer} (on wlan0)
\tsignal:  \t{dbm} dBm
\ttx bitrate:\t{phy} MBit/s MCS {mcs}
\trx bitrate:\t{phy} MBit/s MCS {mcs}
"""
PEERS = {"192.168.1.31": "c4:93:00:57:7c:72", "192.168.1.32": "c4:93:00:57:7c:71",
         "192.168.1.33": "c4:93:00:60:35:e4", "192.168.1.34": "c4:93:00:60:35:e3"}


def write(ip: str, mcs: int | None, dbm: int) -> None:
    text = "" if mcs is None else DUMP.format(peer=PEERS[ip], dbm=dbm, phy=PHY[mcs], mcs=mcs)
    (DIR / f"{ip}.txt").write_text(text)


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ("down", *map(str, PHY)):
        print(__doc__)
        return 2
    DIR.mkdir(exist_ok=True)
    arg = sys.argv[1]
    write("192.168.1.31", 9, -60)
    write("192.168.1.32", 9, -54)
    if arg == "down":
        write("192.168.1.33", None, 0)
        write("192.168.1.34", None, 0)
        print("偽の ODU: 無線1 は MCS 9、無線2 は相手の局がいない (無線断)")
    else:
        mcs = int(arg)
        dbm = -58 if mcs >= 9 else -66
        write("192.168.1.33", mcs, dbm)
        write("192.168.1.34", mcs, dbm - 2)
        print(f"偽の ODU: 無線1 は MCS 9、無線2 は MCS {mcs} (PHY {PHY[mcs]} Mbps)")
    print(f"フォルダ: {DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
