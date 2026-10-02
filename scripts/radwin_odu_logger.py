#!/usr/bin/env python3
"""4台すべての ODU の無線の状態を、長時間にわたって記録し続ける (読み取り専用)。

雨の観測の記録 R1。radwin_telemetry.py は親機 (.31/.33) しか読まないが、
backoff や窓の濡れの影響は向きによって出方が違うので、子機 (.32/.34) も読む。

記録: <出力先>/odu_YYYYMMDD.csv (日付ごとに分ける。時刻は UNIX 秒)
  time        読み取りを終えた時刻
  odu         ODU の IP
  connected   1 = 相手の局とつながっている
  why         つながっていない理由 (ssh_failed = 管理用の通信が届かない /
              no_station = 届いたが相手の局がいない)
  signal_dbm  その ODU が相手から受けた電力
  tx_mcs / rx_mcs / tx_phy_mbps / rx_phy_mbps
  read_s      その ODU の読み取りにかかった秒数 (応答の遅れの手がかり)
  signal_avg_dbm  受信電力の平均 (ドライバの平均値。1 回ごとの値よりゆれが小さい)
  connected_s     つながってからの秒数。前の行より小さくなれば、そのあいだに切れてつながり直した
                  (5 秒ごとの読み取りの合間に起きた短い切断も分かる)
  inactive_ms     最後に通信してからの時間
  dump_tx_bytes / dump_rx_bytes / dump_tx_packets / dump_rx_packets
                  station dump の値そのまま。V90 の親機では rx と tx が逆 (rx bytes = 自分が送った量。
                  2026-10-02 に /sys の tx_bytes と一致することで確認)
  nd_tx_errors / nd_tx_dropped / nd_rx_errors / nd_rx_dropped
                  /sys/class/net/wlan0/statistics の誤りの数。2026-10-02 時点で 18 種類すべて 0
                  (ドライバが数えていない可能性が高い)。0 以外になったときに気づけるよう残す
V90 の station dump には再送 (tx retries) や送信失敗 (tx failed) の項目が無い。

使い方 (通常は radwin_observe.py が起動する):
    sudo python3 scripts/radwin_odu_logger.py --dir <出力先> [--interval 5]
"""
from __future__ import annotations

import argparse
import csv
import re
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from radwin_ssh import ssh_run  # noqa: E402
from radwin_telemetry import parse_dump, SSH_TIMEOUT  # noqa: E402

ODUS = ["192.168.1.31", "192.168.1.32", "192.168.1.33", "192.168.1.34"]
NETDEV = ["tx_errors", "tx_dropped", "rx_errors", "rx_dropped"]
# 1 回の SSH でまとめて読む。ODU のシェルはブレース展開が使えない可能性があるので列挙する
CMD = ("iw dev wlan0 station dump 2>/dev/null; for f in " + " ".join(NETDEV) + "; do "
       "echo \"nd_$f $(cat /sys/class/net/wlan0/statistics/$f 2>/dev/null)\"; done")
DUMP_EXTRA = [("signal_avg_dbm", r"signal avg:\s*(-?\d+)"), ("connected_s", r"connected time:\s*(\d+)"),
              ("inactive_ms", r"inactive time:\s*(\d+)"), ("dump_tx_bytes", r"tx bytes:\s*(\d+)"),
              ("dump_rx_bytes", r"rx bytes:\s*(\d+)"), ("dump_tx_packets", r"tx packets:\s*(\d+)"),
              ("dump_rx_packets", r"rx packets:\s*(\d+)")]
COLUMNS = (["time", "odu", "connected", "why", "signal_dbm", "tx_mcs", "rx_mcs",
            "tx_phy_mbps", "rx_phy_mbps", "read_s"]
           + [k for k, _ in DUMP_EXTRA] + [f"nd_{k}" for k in NETDEV])


def parse_extra(text: str) -> list:
    """station dump の追加項目と /sys の誤りの数を COLUMNS の後半の並びで返す。無ければ空欄。"""
    vals = []
    for _, pat in DUMP_EXTRA:
        m = re.search(pat, text)
        vals.append(m.group(1) if m else "")
    for k in NETDEV:
        m = re.search(rf"^nd_{k} (\d+)\s*$", text, re.M)
        vals.append(m.group(1) if m else "")
    return vals


def read_odu(ip: str) -> list:
    """1台を読み、COLUMNS の並びの1行を返す。"""
    t0 = time.monotonic()
    code, out = ssh_run(ip, CMD, timeout=SSH_TIMEOUT)
    took = time.monotonic() - t0
    if code != 0:
        d, why = {"connected": False}, "ssh_failed"
    else:
        d = parse_dump(out)
        why = "" if d.get("connected") else "no_station"
    g = lambda k: "" if d.get(k) is None else d.get(k)
    return ([f"{time.time():.3f}", ip, int(bool(d.get("connected"))), why,
             g("signal_dbm"), g("tx_mcs"), g("rx_mcs"), g("tx_phy_mbps"), g("rx_phy_mbps"),
             f"{took:.2f}"] + (parse_extra(out) if code == 0 else [""] * (len(DUMP_EXTRA) + len(NETDEV))))


def daily_path(folder: Path, prefix: str, t: float) -> Path:
    return folder / f"{prefix}_{time.strftime('%Y%m%d', time.localtime(t))}.csv"


def append_rows(path: Path, header: list[str], rows: list[list]) -> None:
    """日付ごとのファイルに追記する。新しいファイルなら見出しを先に書く。"""
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="記録の出力先フォルダ")
    ap.add_argument("--interval", type=float, default=5.0,
                    help="1巡 (4台) の開始間隔 [s]。読み取りが長引けば次は直後に始める")
    ap.add_argument("--rounds", type=int, default=0, help="0 = 止められるまで続ける")
    a = ap.parse_args()
    folder = Path(a.dir)
    folder.mkdir(parents=True, exist_ok=True)

    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    n = 0
    try:
        while not stop:
            start = time.monotonic()
            rows = [read_odu(ip) for ip in ODUS]
            append_rows(daily_path(folder, "odu", float(rows[-1][0])), COLUMNS, rows)
            n += 1
            if a.rounds and n >= a.rounds:
                break
            rest = a.interval - (time.monotonic() - start)
            while rest > 0 and not stop:
                time.sleep(min(rest, 0.5))
                rest -= 0.5
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
