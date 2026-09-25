#!/usr/bin/env python3
"""TX power backoff の効き目を、4台すべての ODU から読んで確かめる。読み取り専用。

backoff は設定した ODU の「送信」だけを弱める。その効果は相手側の受信電力に出る。
  親機 (.31/.33) に設定 → 子機 (.32/.34) の受信電力と、親機の送信 MCS が下がる
  子機 (.32/.34) に設定 → 親機 (.31/.33) の受信電力と、子機の送信 MCS が下がる
親機だけを見る radwin_telemetry.py では片方向しか見えないため、4台すべてを読む。

MCS は通信がないと上がらない。比較は radwin_live_monitor.py で負荷をかけた状態で行うこと。

使い方:
    sudo python3 scripts/radwin_backoff_check.py                        # 5回読んで中央値
    sudo python3 scripts/radwin_backoff_check.py --label bo20 --csv docs/backoff_check.csv
    sudo python3 scripts/radwin_backoff_check.py --rounds 60   # 約2分。MCS が行き来するときの割合を見る
"""
from __future__ import annotations
import argparse, csv, statistics, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from radwin_ssh import ssh_run  # noqa: E402
from radwin_telemetry import parse_dump  # noqa: E402

ODUS = [  # (表示名, IP, 相手の IP)
    ("無線1 親機", "192.168.1.31", "192.168.1.32"),
    ("無線1 子機", "192.168.1.32", "192.168.1.31"),
    ("無線2 親機", "192.168.1.33", "192.168.1.34"),
    ("無線2 子機", "192.168.1.34", "192.168.1.33"),
]
# 設定の場所は未確定なので、名前に backoff / power を含む項目を広く読む (表示のみ)
CFG_CMD = ("uci show 2>/dev/null | grep -iE 'backoff|txpow|tx_pow|power' | head -8; "
           "grep -risE 'backoff' /etc/config 2>/dev/null | head -4")


def med(v):
    v = [x for x in v if x is not None]
    return statistics.median(v) if v else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--label", default="", help="CSV に残す条件名 (例: bo0, bo20)")
    ap.add_argument("--csv", default=None, help="結果を追記する CSV")
    ap.add_argument("--no-config", action="store_true", help="設定項目の表示を省く")
    a = ap.parse_args()

    samples = {ip: [] for _, ip, _ in ODUS}
    for r in range(a.rounds):
        for name, ip, _ in ODUS:
            code, out = ssh_run(ip, "iw dev wlan0 station dump 2>/dev/null")
            d = parse_dump(out) if code == 0 else {"connected": False}
            d["t"] = time.time()
            samples[ip].append(d)
        print(f"  読み取り {r + 1}/{a.rounds}", end="\r", flush=True)
        if r + 1 < a.rounds:
            time.sleep(a.interval)
    print()

    rows = []
    print(f"{'ODU':12s} {'受信電力':>9s} {'送信MCS':>7s} {'受信MCS':>7s} {'送信PHY':>9s}  接続")
    for name, ip, peer in ODUS:
        s = samples[ip]
        up = [x for x in s if x.get("connected")]
        row = {"label": a.label, "time": f"{time.time():.0f}", "odu": ip, "name": name,
               "signal_dbm": med([x.get("signal_dbm") for x in up]),
               "tx_mcs": med([x.get("tx_mcs") for x in up]),
               "rx_mcs": med([x.get("rx_mcs") for x in up]),
               "tx_phy_mbps": med([x.get("tx_phy_mbps") for x in up]),
               "connected": f"{len(up)}/{len(s)}"}
        rows.append(row)
        f = lambda v, u="": "-" if v is None else f"{v:g}{u}"
        print(f"{name:12s} {f(row['signal_dbm'], ' dBm'):>9s} {f(row['tx_mcs']):>7s} "
              f"{f(row['rx_mcs']):>7s} {f(row['tx_phy_mbps'], 'M'):>9s}  {row['connected']}")
    # MCS が境目で行き来する場合、中央値だけでは状態を表せない。割合も出す。
    print("\n  送信MCS の内訳 (読み取り回数に占める割合) / 受信電力の範囲")
    for name, ip, _ in ODUS:
        up = [x for x in samples[ip] if x.get("connected")]
        mcs = [x.get("tx_mcs") for x in up if x.get("tx_mcs") is not None]
        sig = [x.get("signal_dbm") for x in up if x.get("signal_dbm") is not None]
        dist = "  ".join(f"MCS{m}:{mcs.count(m) / len(mcs):.0%}" for m in sorted(set(mcs), reverse=True))
        rng = f"{min(sig)}〜{max(sig)} dBm" if sig else "-"
        print(f"    {name:12s} {dist or '-':30s} {rng}")
    print("\n  受信電力 = その ODU が相手から受けた電力 (相手の送信電力の影響を受ける)")
    print("  送信MCS  = その ODU が送る向きの MCS (自分の送信電力の影響を受ける)")

    if not a.no_config:
        print("\n── 送信電力に関係する設定 (読み取りのみ) ──")
        for name, ip, _ in ODUS:
            code, out = ssh_run(ip, CFG_CMD)
            lines = [l for l in out.splitlines() if l.strip()]
            print(f"  {name} ({ip}):" + ("" if lines else " 該当なし"))
            for l in lines:
                print(f"      {l}")

    if a.csv:
        path = Path(a.csv)
        new = not path.exists()
        with path.open("a", newline="") as fp:
            w = csv.DictWriter(fp, fieldnames=list(rows[0]))
            if new:
                w.writeheader()
            w.writerows(rows)
        # 中央値だけでは MCS の行き来が残らないため、1回ごとの読み取りも別ファイルに残す
        raw = path.with_name(path.stem + "_samples.csv")
        new = not raw.exists()
        with raw.open("a", newline="") as fp:
            w = csv.writer(fp)
            if new:
                w.writerow(["label", "time", "odu", "connected", "signal_dbm", "tx_mcs", "rx_mcs"])
            for _, ip, _ in ODUS:
                for x in samples[ip]:
                    w.writerow([a.label, f"{x['t']:.1f}", ip, int(bool(x.get("connected"))),
                                x.get("signal_dbm"), x.get("tx_mcs"), x.get("rx_mcs")])
        print(f"\n追記: {path} / {raw} (1回ごとの値)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
