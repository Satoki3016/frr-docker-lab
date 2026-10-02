#!/usr/bin/env python3
"""雨の観測の記録を検査する: 記録の空白・読めていない列・部品の再起動・全負荷計測の合否。

使い方:
    python3 scripts/radwin_observe_check.py <観測フォルダ>
radwin_observe.py が日付の変わり目と停止時に実行し、check.txt に残す。sudo 不要。

判定:
    [OK] / [NG] は、観測の結果を使ってよいかの目安。NG の行は、その時間帯の記録を使う前に確かめる。
"""
from __future__ import annotations

import csv
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

# 記録ごとの、空白とみなす間隔 [s] (記録の間隔の 3 倍程度)
GAP_LIMITS = {"odu": 30.0, "state": 30.0, "ospf_bfd": 180.0, "controller": 30.0, "weather": 1800.0,
              "nowcast": 900.0, "ping": 30.0}


def fmt(t: float) -> str:
    return time.strftime("%m-%d %H:%M:%S", time.localtime(t))


def read_rows(paths: list[Path]) -> list[dict]:
    rows = []
    for p in sorted(paths):
        with p.open(newline="") as f:
            rows += [r for r in csv.DictReader(f) if r.get("time") and r["time"] != "time"]
    return rows


def gaps(times: list[float], limit: float) -> list[tuple[float, float]]:
    times = sorted(times)
    return [(a, b) for a, b in zip(times, times[1:]) if b - a > limit]


def report_gaps(name: str, times: list[float], limit: float, out: list[str]) -> bool:
    if not times:
        out.append(f"[NG] {name}: 記録なし")
        return False
    g = gaps(times, limit)
    span = max(times) - min(times)
    lost = sum(b - a for a, b in g)
    head = (f"{name}: {len(times)} 行 / {fmt(min(times))}〜{fmt(max(times))} "
            f"/ {limit:.0f} 秒を超える空白 {len(g)} 回 (計 {lost:.0f} 秒 = {lost / span:.1%})" if span else
            f"{name}: {len(times)} 行")
    out.append(("[OK] " if not g else "[NG] ") + head)
    for a, b in g[:10]:
        out.append(f"       {fmt(a)} → {fmt(b)} ({b - a:.0f} 秒)")
    if len(g) > 10:
        out.append(f"       ほか {len(g) - 10} 回")
    return not g


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    obs = Path(sys.argv[1])
    out: list[str] = [f"観測フォルダ: {obs}", f"検査時刻: {fmt(time.time())}", ""]
    ok = True

    # ── 記録の空白 ──
    out.append("■ 記録の空白")
    odu = read_rows(list(obs.glob("odu_*.csv")))
    by_odu = defaultdict(list)
    for r in odu:
        by_odu[r["odu"]].append(float(r["time"]))
    if not by_odu:
        ok &= report_gaps("ODU (R1)", [], GAP_LIMITS["odu"], out)
    for ip in sorted(by_odu):
        ok &= report_gaps(f"ODU {ip} (R1)", by_odu[ip], GAP_LIMITS["odu"], out)
    state = read_rows(list(obs.glob("state_*.csv")))
    ok &= report_gaps("経路表・HTB (R5)", [float(r["time"]) for r in state], GAP_LIMITS["state"], out)
    ospf = read_rows(list(obs.glob("ospf_bfd_*.csv")))
    ok &= report_gaps("OSPF・BFD (R7)", [float(r["time"]) for r in ospf], GAP_LIMITS["ospf_bfd"], out)
    ctl = read_rows([obs / "controller.csv"] if (obs / "controller.csv").exists() else [])
    ok &= report_gaps("動的制御 (R3)", [float(r["time"]) for r in ctl], GAP_LIMITS["controller"], out)
    wx = read_rows(list(obs.glob("weather_*.csv")))
    ok &= report_gaps("気象 (W1)", [float(r["time"]) for r in wx], GAP_LIMITS["weather"], out)
    err = [r for r in wx if r.get("error")]
    if err:
        out.append(f"[注意] 気象の取得に一部失敗: {len(err)}/{len(wx)} 回 (例: {err[0]['error'][:80]})")
    nc = read_rows(list(obs.glob("nowcast_*.csv")))
    ok &= report_gaps("降水ナウキャスト", [float(r["time"]) for r in nc], GAP_LIMITS["nowcast"], out)
    err = [r for r in nc if r.get("error") or r.get("mmh_lo") == "unknown"]
    if err:
        out.append(f"[注意] ナウキャストの取得失敗・未知の色: {len(err)}/{len(nc)} 回")
    pg = read_rows(list(obs.glob("ping_*.csv")))
    ok &= report_gaps("無線区間の ping", [float(r["time"]) for r in pg], GAP_LIMITS["ping"], out)
    if pg:
        rtt = sorted(float(r["rtt_ms"]) for r in pg if r["status"] == "ok")
        lost = sum(r["status"] != "ok" for r in pg)
        med = rtt[len(rtt) // 2] if rtt else float("nan")
        out.append(f"       応答なし・届かず {lost}/{len(pg)} 行 / 往復遅延の中央値 {med:.2f} ms (全負荷計測の時間帯を含む)")

    # ── 読めていない列 (解析の正規表現が実際の表示と合っていない可能性) ──
    out.append("")
    out.append("■ 値が読めていない列 (すべて空欄なら NG)")
    for name, rows, cols in (("state", state, ["t41", "t42", "t43", "htb_leri_cr1", "htb_cr1_lere"]),
                             ("ospf_bfd", ospf, ["ospf_cr1", "bfd_down_egress", "bfd_down_ingress"])):
        for c in cols:
            vals = [r.get(c, "") for r in rows]
            blank = sum(v == "" for v in vals)
            if not vals:
                continue
            mark = "[NG]" if blank == len(vals) else ("[注意]" if blank else "[OK]")
            ok &= mark != "[NG]"
            out.append(f"{mark} {name}.{c}: 空欄 {blank}/{len(vals)}")

    # ── ODU の接続 ──
    out.append("")
    out.append("■ ODU の接続 (読み取り回数に占める割合)")
    for ip in sorted(by_odu):
        rs = [r for r in odu if r["odu"] == ip]
        why = Counter(r["why"] for r in rs if r["connected"] != "1")
        conn = sum(r["connected"] == "1" for r in rs)
        detail = " ".join(f"{k}={v}" for k, v in why.items())
        # つながってからの秒数が前の読み取りより小さくなった回数 = 切れてつながり直した回数
        cs = [int(r["connected_s"]) for r in rs if r.get("connected_s", "").isdigit()]
        re_assoc = sum(b < a for a, b in zip(cs, cs[1:]))
        errs = sum(int(r[c]) for r in rs[-1:] for c in r if c.startswith("nd_") and r[c].isdigit())
        extra = f" / 再接続 {re_assoc} 回" if cs else ""
        extra += f" / 誤りの数 (最後の読み取り) {errs}" if any(c.startswith("nd_") for c in rs[0]) else ""
        out.append(f"  {ip}: 接続 {conn}/{len(rs)} ({conn / len(rs):.1%}) {detail}{extra}")

    # ── 部品の再起動 ──
    out.append("")
    out.append("■ 部品の再起動 (events.csv)")
    ev = read_rows([obs / "events.csv"] if (obs / "events.csv").exists() else [])
    exits = Counter(r["detail"].split()[0] for r in ev if r["event"] == "child_exit")
    if not exits:
        out.append("[OK] 再起動なし")
    for name, n in exits.most_common():
        # 軽い負荷は無線断のあいだ接続できずに止まるので、再起動しても異常とは限らない
        mark = "[注意]" if name == "load_client" else "[NG]"
        ok &= mark != "[NG]"
        out.append(f"{mark} {name}: {n} 回")

    # ── 全負荷計測 ──
    out.append("")
    out.append("■ 全負荷計測 (probes.csv)")
    pr = read_rows([]) if not (obs / "probes.csv").exists() else list(csv.DictReader((obs / "probes.csv").open()))
    if not pr:
        out.append("  まだ 1 回も行われていない")
    by_reason = Counter(r["reason"] for r in pr)
    fails = [r for r in pr if r["result"] != "success"]
    out.append(f"  {len(pr)} 回 (" + ", ".join(f"{k} {v}" for k, v in by_reason.items()) + f") / 失敗 {len(fails)} 回")
    for r in fails[:10]:
        out.append(f"[NG]   {fmt(float(r['start']))} {r['reason']} code={r['exit_code']} {r['folder']}")
    ok &= not fails
    skips = [r for r in ev if r["event"] == "probe_skip"]
    for r in skips:
        out.append(f"[NG]   {fmt(float(r['time']))} 計測を見送り: {r['detail']}")
    ok &= not skips

    # ── BFD の断 ──
    out.append("")
    out.append("■ BFD の断の回数 (観測の始め → 終わり)")
    for col, label in (("bfd_down_egress", "出口側 (無線)"), ("bfd_down_ingress", "入口側")):
        vals = [int(r[col]) for r in ospf if r.get(col, "").isdigit()]
        out.append(f"  {label}: " + (f"{vals[0]} → {vals[-1]} (+{vals[-1] - vals[0]})" if vals else "記録なし"))

    out.append("")
    out.append("総合: " + ("[OK] 記録に欠けはありません" if ok else "[NG] 上の NG を確かめてから記録を使ってください"))
    print("\n".join(out))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
