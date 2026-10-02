#!/usr/bin/env python3
"""経路表・HTB・軽い負荷・OSPF/BFD の状態を、長時間にわたって記録し続ける (読み取り専用)。

雨の観測の記録 R5 (経路表)・R7 (OSPF/BFD)・R8 (軽い負荷)。

記録 (日付ごとに分ける。時刻は UNIX 秒):
  state_YYYYMMDD.csv     10 秒ごと
    t41 / t42 / t43        LER_Ingress のポリシー経路表。"leri-cr1=13 leri-cr2=100 leri-cr3=100" の形
    htb_leri_cr1 / htb_cr1_lere  CR1 経路の HTB のルートの整形レート (tc の表記のまま)
    load                   軽い負荷 (iperf3, 5301 番) の送信側が動いていれば 1
  ospf_bfd_YYYYMMDD.csv  60 秒ごと
    ospf_cr1               CR1 から見た OSPF 隣接。"192.168.0.5=Full 192.168.0.1=Full" の形
    bfd_down_egress / bfd_down_ingress  CR1 の BFD の Session down events の累計
                           (出口側 = 無線側 peer 10.0.2.2 / 入口側 = peer 10.0.1.1)

読めなかった値は空欄にする (0 と区別するため)。

使い方 (通常は radwin_observe.py が起動する):
    sudo python3 scripts/radwin_state_logger.py --dir <出力先>
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

STATE_COLUMNS = ["time", "t41", "t42", "t43", "htb_leri_cr1", "htb_cr1_lere", "load"]
OSPF_COLUMNS = ["time", "ospf_cr1", "bfd_down_egress", "bfd_down_ingress"]
EGRESS_PEER, INGRESS_PEER = "10.0.2.2", "10.0.1.1"
LOAD_PATTERN = "iperf3 -c 10.0.2.2 -p 5301"


def sh(args: list[str], timeout: float = 10.0) -> str | None:
    """コマンドの標準出力。失敗・時間切れは None (空欄として記録する)。"""
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return p.stdout if p.returncode == 0 else None


def parse_routes(text: str | None) -> str:
    """ip route show table N の出力を "dev=weight ..." にする。経路なしは "none"。"""
    if text is None:
        return ""
    hops = re.findall(r"dev (\S+)(?: weight (\d+))?", text)
    if not hops:
        return "none"
    return " ".join(f"{dev}={w or 1}" for dev, w in hops)


def parse_htb_root(text: str | None) -> str:
    """tc class show の出力から、ルートクラス 1:0 の rate を抜く。"""
    if text is None:
        return ""
    # classid 1:0 は tc の表示で "1:" になることがあるため、どちらも受ける
    m = re.search(r"class htb 1:0?\s+root\b.*?\brate (\S+)", text)
    return m.group(1) if m else ""


def parse_ospf(text: str | None) -> str:
    """show ip ospf neighbor の出力を "routerid=State ..." にする。隣接なしは "none"。"""
    if text is None:
        return ""
    pairs = re.findall(r"^(\d+\.\d+\.\d+\.\d+)\s+\d+\s+(\w+)", text, re.M)
    return " ".join(f"{rid}={st}" for rid, st in pairs) or "none"


def parse_bfd_down(text: str | None, peer: str) -> str:
    """show bfd peers counters の出力から、peer ごとの Session down events を抜く。"""
    if text is None:
        return ""
    for block in re.split(r"\n\s*(?=peer )", "\n" + text):
        if re.match(rf"\s*peer {re.escape(peer)}\b", block):
            m = re.search(r"Session down events:\s*(\d+)", block)
            return m.group(1) if m else ""
    return ""


def read_state() -> list:
    routes = [parse_routes(sh(["ip", "netns", "exec", "LER_Ingress",
                               "ip", "route", "show", "table", str(t)])) for t in (41, 42, 43)]
    htb = [parse_htb_root(sh(["ip", "netns", "exec", ns, "tc", "class", "show", "dev", dev]))
           for ns, dev in (("LER_Ingress", "leri-cr1"), ("CR1", "cr1-lere"))]
    load = int(sh(["pgrep", "-f", LOAD_PATTERN]) is not None)
    return [f"{time.time():.3f}", *routes, *htb, load]


def read_ospf_bfd() -> list:
    ospf = parse_ospf(sh(["docker", "exec", "frr-CR1", "vtysh", "-c", "show ip ospf neighbor"]))
    bfd = sh(["docker", "exec", "frr-CR1", "vtysh", "-c", "show bfd peers counters"])
    return [f"{time.time():.3f}", ospf, parse_bfd_down(bfd, EGRESS_PEER),
            parse_bfd_down(bfd, INGRESS_PEER)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--state-interval", type=float, default=10.0)
    ap.add_argument("--ospf-interval", type=float, default=60.0)
    a = ap.parse_args()
    folder = Path(a.dir)
    folder.mkdir(parents=True, exist_ok=True)

    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    next_state = next_ospf = time.monotonic()
    try:
        while not stop:
            now = time.monotonic()
            if now >= next_state:
                row = read_state()
                append_rows(daily_path(folder, "state", float(row[0])), STATE_COLUMNS, [row])
                next_state = now + a.state_interval
            if now >= next_ospf:
                row = read_ospf_bfd()
                append_rows(daily_path(folder, "ospf_bfd", float(row[0])), OSPF_COLUMNS, [row])
                next_ospf = now + a.ospf_interval
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
