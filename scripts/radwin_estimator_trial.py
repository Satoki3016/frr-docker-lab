#!/usr/bin/env python3
"""prs-link-estimator を条件を変えて繰り返し実行し、再現性を確かめる。

1回の結果 (mainMcs=3, estimatedThroughput=673, rssi=0) だけで
「信用できない」と断じたため、検証する。

確かめる点:
  ・値が毎回同じか (固定値なら実測していない)
  ・rssi/snr が埋まることがあるか
  ・トラフィックの有無で結果が変わるか
    -a は「リンクが idle のとき ping flood する」仕様なので、
    負荷がある状態では既存トラフィックから測るはず
"""
from __future__ import annotations
import argparse, json, os, re, signal, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from radwin_ssh import ssh_run  # noqa: E402

AP, STA = "192.168.1.31", "192.168.1.32"
LOAD_PORT, LOAD_DST = 5301, "10.0.2.2"
FIELDS = ["mainMcs", "estimatedThroughput", "currentThroughput",
          "numRxMpdus", "numTxDrops", "rssi", "snr", "distance", "linkHealth"]


def run_est(with_flood: bool, secs: int) -> tuple[dict | None, str]:
    """成功例と同じ引数順にする (-j は最後)。失敗時は生の出力も返す。"""
    cmd = "prs-link-estimator -i wlan0"
    if with_flood:
        cmd += f" -a {STA} -s 1400"
    cmd += f" -t {secs} -j"
    _, out = ssh_run(AP, cmd + " 2>&1", timeout=secs + 30.0)
    out = out or ""
    # このツールは JSON オブジェクトを複数個続けて出力する。
    # 1個だけと決めつけると "Extra data" で失敗するため、順に読み取る。
    objs, dec, i = [], json.JSONDecoder(), 0
    while i < len(out):
        j = out.find("{", i)
        if j < 0:
            break
        try:
            o, end = dec.raw_decode(out, j)
            objs.append(o)
            i = end
        except json.JSONDecodeError:
            i = j + 1
    if not objs:
        return None, out
    # 最後のオブジェクトが集計結果とみなす
    return objs[-1], f"(JSON {len(objs)} 個を取得。最後のものを使用)"


def mcs_now() -> str:
    _, out = ssh_run(AP, "iw dev wlan0 station dump 2>/dev/null | grep 'tx bitrate'",
                     timeout=15.0)
    m = re.search(r"MCS\s*(\d+)", out or "")
    return m.group(1) if m else "?"


def start_load(streams: int) -> list[subprocess.Popen]:
    p = [subprocess.Popen(["ip", "netns", "exec", "LER_Egress", "iperf3", "-s",
                           "-p", str(LOAD_PORT)], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, start_new_session=True)]
    time.sleep(0.6)
    p.append(subprocess.Popen(["ip", "netns", "exec", "CR1", "iperf3", "-c", LOAD_DST,
                               "-p", str(LOAD_PORT), "-t", "86400", "-P", str(streams)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              start_new_session=True))
    return p


def stop_load(ps: list[subprocess.Popen]) -> None:
    for pr in ps:
        try:
            os.killpg(os.getpgid(pr.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass


def trial(label: str, n: int, with_flood: bool, secs: int) -> None:
    _, sample = run_est(with_flood, 1) if False else (None, "")
    cmdshow = "prs-link-estimator -i wlan0" + (f" -a {STA} -s 1400" if with_flood else "") + f" -t {secs} -j"
    print(f"\n■ {label}  ({n} 回)")
    print(f"  $ {cmdshow}")
    print(f"  {'#':>2} {'iw':>3} " + " ".join(f"{f[:13]:>14}" for f in FIELDS[:5]))
    rows = []
    for i in range(n):
        mcs = mcs_now()
        d, raw = run_est(with_flood, secs)
        if d is None:
            print(f"  {i+1:2d} {mcs:>7}  取得失敗 — ツールの生出力:")
            for l in (raw.strip() or "(出力なし)").splitlines()[:12]:
                print(f"        | {l}")
            continue
        rows.append(d)
        print(f"  {i+1:2d} {mcs:>3} " +
              " ".join(f"{str(d.get(f,'-'))[:14]:>14}" for f in FIELDS[:5]))
    if len(rows) > 1:
        print("  --- 変動の有無 ---")
        for f in FIELDS:
            vs = {r.get(f) for r in rows}
            state = "固定" if len(vs) == 1 else f"変動 ({min(vs)}〜{max(vs)})" \
                if all(isinstance(v, (int, float)) for v in vs) else "変動"
            print(f"      {f:22s} {state}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--time", type=int, default=5)
    ap.add_argument("--streams", type=int, default=4)
    a = ap.parse_args()

    print("=" * 78)
    print("prs-link-estimator の再現性確認")
    print("=" * 78)

    trial("条件A: 無負荷 + ping flood (-a あり)", a.repeat, True, a.time)
    trial("条件B: 無負荷 + flood なし", a.repeat, False, a.time)

    print(f"\n負荷を投入します (CR1 → {LOAD_DST}, {a.streams} ストリーム) ...")
    ps = start_load(a.streams)
    try:
        time.sleep(4)
        trial("条件C: 負荷あり + flood なし", a.repeat, False, a.time)
        trial("条件D: 負荷あり + ping flood", a.repeat, True, a.time)
    finally:
        stop_load(ps)
        print("\n負荷を停止しました")

    print("\n" + "=" * 78)
    print("判定:")
    print("  全条件で値が固定    → 実測していない。ツールは使えない")
    print("  負荷時だけ値が動く  → 既存トラフィックから測る仕様。使える可能性あり")
    print("  rssi/snr が埋まる   → 一部の条件では有効")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
