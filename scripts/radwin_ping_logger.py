#!/usr/bin/env python3
"""無線区間 (CR1 → LER_Egress、10.0.2.2) に 1 秒ごとに ping を打ち、往復遅延と応答の有無を記録し続ける。

全負荷計測は 15 分ごとの約 2 分だけなので、そのあいだの無線の品質を連続で追うための記録。
ICMP は fwmark を持たないので HTB の整形を通らない (無線区間の素の往復遅延)。
全負荷計測のあいだは、無線区間が混むため遅延が増える。分析では probes.csv の時間帯を除くか、別に扱う。

記録: <観測フォルダ>/ping_YYYYMMDD.csv
  time     ping が表示した時刻 (UNIX 秒。-D)
  seq      icmp_seq
  rtt_ms   往復遅延 [ms] (応答がなければ空欄)
  status   ok / no_answer (1 秒以内に応答なし) / unreachable (宛先に届かない) / other
  遅れて届いた応答は、no_answer の行のあとに同じ seq の ok の行として現れる。

使い方 (通常は radwin_observe.py が起動する):
    sudo python3 scripts/radwin_ping_logger.py --dir <観測フォルダ>
"""
from __future__ import annotations

import argparse
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from radwin_odu_logger import append_rows, daily_path  # noqa: E402

TARGET = "10.0.2.2"
COLUMNS = ["time", "seq", "rtt_ms", "status"]
_RE_TS = re.compile(r"^\[(\d+\.\d+)\]\s*(.*)$")
_RE_OK = re.compile(r"icmp_seq=(\d+) .*time=([\d.]+) ms")
_RE_NO = re.compile(r"no answer yet for icmp_seq=(\d+)")
_RE_UNREACH = re.compile(r"icmp_seq=(\d+) .*Unreachable", re.I)


def parse_line(line: str) -> list | None:
    """ping -D -O の 1 行 → [time, seq, rtt_ms, status]。記録しない行は None。"""
    m = _RE_TS.match(line.strip())
    if not m:
        return None
    t, body = m.group(1), m.group(2)
    if (k := _RE_OK.search(body)):
        return [t, k.group(1), k.group(2), "ok"]
    if (k := _RE_NO.search(body)):
        return [t, k.group(1), "", "no_answer"]
    if (k := _RE_UNREACH.search(body)):
        return [t, k.group(1), "", "unreachable"]
    if "icmp_seq=" in body:
        k = re.search(r"icmp_seq=(\d+)", body)
        return [t, k.group(1), "", "other"]
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--netns", default="CR1")
    ap.add_argument("--target", default=TARGET)
    a = ap.parse_args()
    folder = Path(a.dir)
    # stdbuf -oL: パイプ越しでも 1 行ずつ出させる (既定ではブロック単位でまとめて出る)
    proc = subprocess.Popen(["ip", "netns", "exec", a.netns, "stdbuf", "-oL",
                             "ping", "-D", "-O", "-n", "-i", "1", "-W", "1", a.target],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def _stop(*_):
        proc.terminate()
    signal.signal(signal.SIGTERM, _stop)
    try:
        for line in proc.stdout:
            row = parse_line(line)
            if row:
                append_rows(daily_path(folder, "ping", float(row[0])), COLUMNS, [row])
    except KeyboardInterrupt:
        proc.terminate()
    proc.wait()
    return proc.returncode or 0


if __name__ == "__main__":
    sys.exit(main())
