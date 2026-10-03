#!/usr/bin/env python3
"""雨の観測 (radwin_observe.py) の記録を、1 本の時間軸にそろえて集計する。観測中でも何度でも作り直せる。

出力 (<観測フォルダ>/summary/):
  probes_summary.csv   全負荷計測 1 回につき 1 行
      時刻 (日本時間)・理由・合否
      / AF41〜43 の受信スループット [Gbps]: throughput.csv の毎秒の受信量の平均 (始めの 10 秒と終わりの 5 秒を除く)
      / AF41〜43 の損失率 [%]: iperf3 の receiver 行の 失った数 / 送った数 (表示の % は丸められているので使わない)
      / 計測中の CR1 の整形レートと重み (計測中に変わったら changed=1)
      / 計測中の 4 台の受信電力の中央値と、親機 (.31/.33) の送信 MCS の最頻値
      / 計測直前 5 分の ping (往復遅延の中央値・応答なしの割合。全負荷の影響を受けない時間帯)
      / 計測の中央の時刻に最も近い気象 (アメダス名古屋・実験場所のナウキャスト)
  timeline.{pdf,png}   時系列の図 (横軸は日本時間)
      (a) 降水強度  (b) 受信電力 (4 台)  (c) 送信 MCS  (d) CR1 の整形レート
      (e) 無線区間の往復遅延 (全負荷計測の時間帯を除く)  (f) 全負荷計測ごとの各クラスの受信量
          (Rx のインタフェースで数えたバイト数。IP/UDP ヘッダを含むので iperf3 の値より約 0.6% 大きい)

  reports/report_YYYYMMDD_HHMM.md (と同名の .png)   --report を付けたときだけ。直近 N 時間の途中経過の報告書
      観測の健全さ・雨・無線・制御・全負荷計測・ping の要点と、注意すべき点。latest_report.md は最新の写し
      radwin_observe.py が日本時間の 0・6・12・18 時に自動で作る

使い方 (2026-10-03 以降に始めた観測は sudo 不要。それより前の観測中のフォルダは sudo が要る):
    sudo python3 results/frr/tools/summarize_rain_observation.py --dir 20261002_rainobs_04
    python3 results/frr/tools/summarize_rain_observation.py --dir <フォルダ> --from 2026-10-03T06:00 --to 2026-10-03T18:00
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import glob
import json
import os
import re
import statistics as st
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from result_paths import result_dir  # noqa: E402
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.font_manager as fm  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402

for _f in ["Noto Sans CJK JP", "TakaoPGothic", "IPAPGothic"]:
    if any(_f.lower() in p.name.lower() for p in fm.fontManager.ttflist):
        matplotlib.rcParams["font.family"] = _f
        break
matplotlib.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white",
    "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 0.8,
    "axes.labelsize": 9, "axes.titlesize": 9, "axes.titlepad": 4, "axes.labelpad": 3,
    "xtick.labelsize": 8, "ytick.labelsize": 8, "legend.fontsize": 7.5,
    "legend.framealpha": 0.95, "legend.edgecolor": "0.8"})

JST = dt.timezone(dt.timedelta(hours=9))
ODUS = [("192.168.1.31", ".31 受信 (無線1 .32→.31)", "#009E73", "-"),
        ("192.168.1.32", ".32 受信 (無線1 .31→.32)", "#009E73", "--"),
        ("192.168.1.33", ".33 受信 (無線2 .34→.33)", "#CC79A7", "-"),
        ("192.168.1.34", ".34 受信 (無線2 .33→.34)", "#CC79A7", "--")]
CLASSES = [("af41", "AF41 (高)", "#0072B2"), ("af42", "AF42 (中)", "#E69F00"), ("af43", "AF43 (低)", "#D55E00")]


# ── 読み込み ─────────────────────────────────────────────────────
def rows(folder: Path, pattern: str) -> list[dict]:
    out = []
    for f in sorted(glob.glob(str(folder / pattern))):
        with open(f, newline="") as fp:
            out += [r for r in csv.DictReader(fp) if r.get("time") not in (None, "", "time")]
    return out


def num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def jst_epoch(s: str) -> float:
    """'2026-10-02T21:20' (日本時間) → UNIX 秒。"""
    return dt.datetime.fromisoformat(s).replace(tzinfo=JST).timestamp()


def fmt(t: float) -> str:
    return dt.datetime.fromtimestamp(t, JST).strftime("%Y-%m-%d %H:%M:%S")


def iperf_loss_pct(path: Path) -> float:
    """iperf3 の最後の [SUM] … receiver 行の 失った数/送った数 → 損失率 [%]。無ければ nan。"""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return float("nan")
    m = re.findall(r"\[SUM\].*?\s(\d+)/(\d+) \([^)]*\)\s+receiver", text)
    if not m:
        return float("nan")
    lost, total = map(int, m[-1])
    return 100.0 * lost / total if total else float("nan")


def steady_gbps(path: Path) -> dict[str, float]:
    """throughput.csv (毎秒の受信量 [bytes/s]) の平均 [Gbps]。始めの 10 秒と終わりの 5 秒を除く。"""
    try:
        data = list(csv.DictReader(path.open()))
    except OSError:
        return {}
    if not data:
        return {}
    last = max(int(num(r["time"])) for r in data)
    body = [r for r in data if 10 <= num(r["time"]) <= last - 5]
    return {k: st.mean(num(r[f"rx{i}_bytes_per_sec"]) * 8 / 1e9 for r in body) if body else float("nan")
            for i, k in ((1, "af41"), (2, "af42"), (3, "af43"))}


def window(data: list[dict], t0: float, t1: float, key: str = "time") -> list[dict]:
    return [r for r in data if t0 <= num(r[key]) <= t1]


def median(vals) -> float:
    v = [x for x in vals if x == x]
    return st.median(v) if v else float("nan")


def mode(vals) -> str:
    v = [x for x in vals if x not in ("", None)]
    return Counter(v).most_common(1)[0][0] if v else ""


# ── 集計表 ───────────────────────────────────────────────────────
def probe_rows(obs: Path, ctl, odu, ping, wx, nc) -> list[dict]:
    out = []
    pcsv = obs / "probes.csv"
    if not pcsv.exists():
        return out
    probes = list(csv.DictReader(pcsv.open()))
    spans = [(num(p["start"]), num(p["end"])) for p in probes]
    for p in probes:
        folder = obs / "probes" / p["folder"] / "frr_observe"
        # 計測の時間帯: timebase.txt (t=0) から 120 秒。無ければ probes.csv の開始・終了
        t0, t1 = num(p["start"]), num(p["end"])
        tb = folder / "timebase.txt"
        if tb.exists():
            m = re.search(r"throughput_t0_epoch_ms=(\d+)", tb.read_text())
            if m:
                t0 = int(m.group(1)) / 1000
                t1 = t0 + 120
        r = {"start_jst": fmt(t0), "reason": p["reason"], "result": p["result"], "folder": p["folder"]}
        thr = steady_gbps(folder / "throughput.csv")
        for key, _, _ in CLASSES:
            r[f"{key}_gbps"] = round(thr.get(key, float("nan")), 3)
            r[f"{key}_loss_pct"] = round(iperf_loss_pct(folder / f"iperf3_{key}.log"), 4)
        c = window(ctl, t0, t1)
        applied = [num(x["applied_mbps"]) for x in c]
        w1 = [x["w1"] for x in c]
        r["cr1_applied_mbps"] = median(applied)
        r["cr1_w1"] = mode(w1)
        r["changed"] = int(len(set(applied)) > 1 or len(set(w1)) > 1)
        o = window(odu, t0, t1)
        for ip, *_ in ODUS:
            r[f"dbm_{ip[-2:]}"] = median(num(x["signal_dbm"]) for x in o if x["odu"] == ip)
        for ip in ("192.168.1.31", "192.168.1.33"):
            r[f"txmcs_{ip[-2:]}"] = mode(x["tx_mcs"] for x in o if x["odu"] == ip)
        # 計測直前 5 分の ping。ほかの計測の時間帯は除く
        pw = [x for x in window(ping, t0 - 300, t0 - 5)
              if not any(a - 5 <= num(x["time"]) <= b + 5 for a, b in spans)]
        rtt = [num(x["rtt_ms"]) for x in pw if x["status"] == "ok"]
        r["ping_rtt_med_ms"] = median(rtt)
        r["ping_noanswer_pct"] = round(100 * sum(x["status"] != "ok" for x in pw) / len(pw), 2) if pw else float("nan")
        mid = (t0 + t1) / 2
        w = [x for x in wx if x.get("obs_time") and jst_epoch(x["obs_time"]) <= mid]
        w = max(w, key=lambda x: jst_epoch(x["obs_time"])) if w else {}
        for k in ("obs_time", "weather_name", "temp", "humidity", "dew_point", "precipitation10m",
                  "precipitation1h", "wind", "wind_dir_name"):
            r[f"amedas_{k}"] = w.get(k, "")
        n = [x for x in nc if x.get("valid_jst")]
        n = min(n, key=lambda x: abs(jst_epoch(x["valid_jst"]) - mid)) if n else {}
        r["nowcast_valid_jst"] = n.get("valid_jst", "")
        r["nowcast_mmh"] = f"{n['mmh_lo']}-{n['mmh_hi']}" if n else ""
        out.append(r)
    return out


# ── 図 ──────────────────────────────────────────────────────────
def per_minute(data: list[dict], value, keep=lambda r: True) -> tuple[list, list]:
    """1 分ごとの中央値。5 秒・1 秒ごとの値をそのまま何日分も描くと線が潰れるため。"""
    buckets: dict[int, list] = {}
    for r in data:
        if keep(r):
            v = value(r)
            if v == v:
                buckets.setdefault(int(num(r["time"]) // 60), []).append(v)
    ks = sorted(buckets)
    return [dt.datetime.fromtimestamp(k * 60 + 30, JST) for k in ks], [st.median(buckets[k]) for k in ks]


def plot(obs: Path, out: Path, ctl, odu, ping, wx, nc, summary, t_from, t_to) -> None:
    fig, ax = plt.subplots(6, 1, figsize=(7.4, 10.6), sharex=True,
                           gridspec_kw={"height_ratios": [1, 1.2, 0.8, 0.8, 0.9, 1.1], "hspace": 0.28})
    letters = "abcdef"

    # (a) 降水強度。ナウキャストは階級の幅 (下限〜上限) を帯で、アメダスは 10 分間降水量を 6 倍して mm/h に換算
    a = ax[0]
    for x in nc:
        if x.get("valid_jst") and x["mmh_lo"] not in ("", "unknown"):
            t = dt.datetime.fromisoformat(x["valid_jst"]).replace(tzinfo=JST)
            hi = num(x["mmh_hi"]) if x["mmh_hi"] != "" else 100.0
            if hi > 0:
                a.bar(t, hi - num(x["mmh_lo"]), bottom=num(x["mmh_lo"]), width=5 / 1440, align="edge",
                      color="#56B4E9", alpha=0.6, lw=0)
    wt = [dt.datetime.fromisoformat(x["obs_time"]).replace(tzinfo=JST) for x in wx if x.get("obs_time")]
    wp = [num(x["precipitation10m"]) * 6 for x in wx if x.get("obs_time")]
    a.step(wt, wp, where="pre", color="#0072B2", lw=1.0)
    a.legend(handles=[Patch(color="#56B4E9", alpha=0.6, lw=0, label="実験場所 (ナウキャストの階級の幅)"),
                      plt.Line2D([], [], color="#0072B2", lw=1.0, label="アメダス名古屋 (10 分間降水量 × 6)")],
             loc="upper left")
    a.set_ylabel("降水強度 [mm/h]")
    a.set_ylim(0, max([5.0] + [x * 1.15 for x in wp if x == x]))   # 雨が無くても目盛りの意味が分かる範囲

    # (b) 受信電力 (1 分ごとの中央値)。再接続 (つながってからの秒数が戻った) を縦線で示す
    b = ax[1]
    for ip, label, color, ls in ODUS:
        sub = [x for x in odu if x["odu"] == ip]
        t, v = per_minute(sub, lambda r: num(r["signal_dbm"]))
        b.plot(t, v, color=color, ls=ls, lw=0.9, label=label)
        cs = [(num(x["time"]), num(x.get("connected_s"))) for x in sub if x.get("connected_s")]
        for (_, c0), (t1, c1) in zip(cs, cs[1:]):
            if c1 < c0:
                b.axvline(dt.datetime.fromtimestamp(t1, JST), color=color, lw=0.6, alpha=0.7)
    b.set_ylabel("受信電力 [dBm]")
    lo_b, hi_b = b.get_ylim()
    b.set_ylim(lo_b - 0.45 * (hi_b - lo_b), hi_b)     # 凡例を下に置く余白 (線と重ねない)
    b.legend(loc="lower left", ncol=2)

    # (c) 送信 MCS (トラフィックの向き = 親機の送信)
    c = ax[2]
    for ip, label, color in (("192.168.1.31", "無線1 (.31→.32)", "#009E73"),
                             ("192.168.1.33", "無線2 (.33→.34)", "#CC79A7")):
        t, v = per_minute([x for x in odu if x["odu"] == ip], lambda r: num(r["tx_mcs"]))
        c.step(t, v, where="mid", color=color, lw=0.9, label=label)
    c.set_ylabel("送信 MCS")
    c.yaxis.set_major_locator(MaxNLocator(integer=True))
    lo_c, hi_c = c.get_ylim()
    c.set_ylim(lo_c - 0.5 - 0.6 * (hi_c - lo_c + 1), hi_c + 0.5)   # 凡例の余白と、線が枠に重ならない余白
    c.legend(loc="lower left", ncol=2)

    # (d) CR1 の整形レート。重み 0 (CR1 を外した) の時間帯を網掛け
    d = ax[3]
    t, v = per_minute(ctl, lambda r: num(r["applied_mbps"]))
    d.step(t, [x / 1000 for x in v], where="mid", color="0.25", lw=1.0)
    down = [dt.datetime.fromtimestamp(num(r["time"]), JST) for r in ctl if r["w1"] == "0"]
    for x in down:
        d.axvspan(x, x + dt.timedelta(seconds=2), color="#D55E00", alpha=0.25, lw=0)
    d.set_ylabel("CR1 整形\nレート [Gbps]")
    d.set_ylim(bottom=0)

    # (e) 往復遅延。全負荷計測の時間帯 (遅延が増える) は除く
    e = ax[4]
    busy = busy_spans(obs, max([num(r["time"]) for r in ping] or [0]))
    keep = lambda r: r["status"] == "ok" and not any(a - 5 <= num(r["time"]) <= b + 5 for a, b in busy)
    t, v = per_minute(ping, lambda r: num(r["rtt_ms"]), keep)
    e.plot(t, v, color="0.25", lw=0.8)
    lost = [dt.datetime.fromtimestamp(num(r["time"]), JST) for r in ping if r["status"] != "ok"
            and not any(a - 5 <= num(r["time"]) <= b + 5 for a, b in busy)]
    if lost:
        e.plot(lost, [0] * len(lost), "|", color="#D55E00", ms=6, label="応答なし・届かず (平常時)")
        e.legend(loc="upper left")
    e.set_ylabel("往復遅延 [ms]\n(1 分の中央値)")
    e.set_ylim(bottom=0)

    # (f) 全負荷計測ごとのスループット
    f = ax[5]
    for key, label, color in CLASSES:
        pts = [(dt.datetime.fromisoformat(s["start_jst"]).replace(tzinfo=JST), s[f"{key}_gbps"])
               for s in summary if s[f"{key}_gbps"] == s[f"{key}_gbps"]]
        if pts:   # 計測と計測のあいだは測っていないので、線でつながない
            f.plot(*zip(*pts), "o", ms=3.5, color=color, label=label)
    f.set_ylabel("受信量 [Gbps]\n(Rx の IF・ヘッダ込み)")
    f.set_ylim(0, 9)
    f.legend(loc="lower left", ncol=3)

    for i, axi in enumerate(ax):
        axi.set_title(f"({letters[i]})", loc="left", fontweight="bold")
        axi.grid(axis="y", lw=0.4, color="0.9")
    loc = mdates.AutoDateLocator(tz=JST)
    ax[-1].xaxis.set_major_locator(loc)
    ax[-1].xaxis.set_major_formatter(mdates.ConciseDateFormatter(
        loc, tz=JST, formats=["%Y", "%m月", "%m/%d", "%H:%M", "%H:%M", "%S秒"],
        offset_formats=["", "%Y年", "%Y年%m月", "%Y年%m月%d日", "%Y年%m月%d日", "%Y年%m月%d日 %H:%M"]))
    ax[-1].set_xlabel("日本時間")
    # 横軸は観測の記録がある範囲 (気象は観測の始まりより前の時刻を含むため、それに合わせない)
    ts = [num(r["time"]) for r in odu + ctl]
    lo = t_from or (min(ts) if ts else None)
    hi = t_to or (max(ts) if ts else None)
    if lo and hi:
        pad = 0.01 * (hi - lo)              # 端の点が枠に切られないように
        ax[-1].set_xlim(dt.datetime.fromtimestamp(lo - pad, JST), dt.datetime.fromtimestamp(hi + pad, JST))
    fig.align_ylabels(ax)
    fig.savefig(out.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(out.with_suffix(".png"), dpi=200, bbox_inches="tight")
    plt.close(fig)


def busy_spans(obs: Path, until: float) -> list[tuple[float, float]]:
    """全負荷計測の時間帯 (events.csv の probe_start〜probe_end)。実行中の回は until までとする。

    probes.csv には終わった回しか載らないため、それだけを使うと、実行中の計測の最中の
    ping の応答なしを「平常時」として数えてしまう (2026-10-03 19:00 に発生)。
    """
    spans, start = [], None
    for r in rows(obs, "events.csv"):
        if r["event"] == "probe_start":
            start = num(r["time"])
        elif r["event"] in ("probe_end", "probe_abort") and start is not None:
            spans.append((start, num(r["time"])))
            start = None
    if start is not None:
        spans.append((start, until))
    return spans


def pct(n: float, d: float) -> str:
    return f"{100 * n / d:.2f}%" if d else "-"


def build_report(obs: Path, t0: float, t1: float, ctl, odu, ping, wx, nc, summary) -> tuple[str, list[str]]:
    """直近の期間の要点を、日本語の Markdown にする。戻り値は (本文, 注意点のリスト)。"""
    L, warn = [], []
    hours = (t1 - t0) / 3600
    L += [f"# 雨の観測 途中経過 ({fmt(t0)[5:16]} 〜 {fmt(t1)[5:16]}、{hours:.0f} 時間)", "",
          f"観測フォルダ: `{obs.name}`", ""]

    # 観測の健全さ
    ev = [r for r in rows(obs, "events.csv") if t0 <= num(r["time"]) <= t1]
    exits = Counter(r["detail"].split()[0] for r in ev if r["event"] == "child_exit")
    gaps = []
    for name, data, limit in (("ODU", odu, 30), ("制御", ctl, 30), ("ping", ping, 30)):
        ts = sorted(num(r["time"]) for r in data)
        g = [b - a for a, b in zip(ts, ts[1:]) if b - a > limit]
        if not ts:
            gaps.append(f"{name}: 記録なし")
        elif g:
            gaps.append(f"{name}: {len(g)} 回 (最長 {max(g):.0f} 秒)")
    fails = [s for s in summary if s["result"] != "success"]
    L += ["## 観測の状態", "",
          f"- 記録の空白: {'なし' if not gaps else ' / '.join(gaps)}",
          f"- 部品の再起動: {'なし' if not exits else ', '.join(f'{k} {v} 回' for k, v in exits.items())}",
          f"- 全負荷計測: {len(summary)} 回 (失敗 {len(fails)} 回)", ""]
    if gaps:
        warn.append("記録に空白がある")
    if [k for k in exits if k != "load_client"]:
        warn.append("部品が再起動した: " + ", ".join(k for k in exits if k != "load_client"))
    if fails:
        warn.append(f"全負荷計測の失敗 {len(fails)} 回")

    # 雨
    ncw = [r for r in nc if r.get("valid_jst") and t0 <= jst_epoch(r["valid_jst"]) <= t1]
    rain = [r for r in ncw if r["mmh_hi"] not in ("", "0")]
    near = [r for r in ncw if r["area_max_hi"] not in ("", "0")]
    wxw = [r for r in wx if r.get("obs_time") and t0 <= jst_epoch(r["obs_time"]) <= t1]
    p10 = [num(r["precipitation10m"]) for r in wxw if r["precipitation10m"] != ""]
    temps = [num(r["temp"]) for r in wxw if r["temp"] != ""]
    spread = [num(r["temp"]) - num(r["dew_point"]) for r in wxw if r.get("dew_point") not in ("", None)]
    hi = max((999 if r["mmh_hi"] == "" else num(r["mmh_hi"])) for r in rain) if rain else 0
    L += ["## 雨と気象", "",
          f"- 実験場所 (ナウキャスト): " + (f"雨あり {len(rain)}/{len(ncw)} 回 (5 分ごと)、最も強い階級の上限 {hi:g} mm/h"
                                        if rain else f"雨なし ({len(ncw)} 回すべて)")
          + (f"。周囲 約 ±300 m では {len(near)} 回" if near and len(near) != len(rain) else ""),
          f"- アメダス名古屋: 降水量の合計 {sum(p10):.1f} mm、10 分間の最大 {max(p10) if p10 else 0:.1f} mm、"
          f"天気 {', '.join(f'{k} {v}' for k, v in Counter(r['weather_name'] for r in wxw if r['weather_name']).items()) or '-'}",
          f"- 気温 {min(temps):.1f}〜{max(temps):.1f}℃、気温と露点の差の最小 {min(spread):.1f}℃ (小さいほど結露しやすい)"
          if temps and spread else "- 気温: 記録なし", ""]
    if rain:
        warn.append(f"実験場所で雨を観測 (最大 {hi:g} mm/h の階級)")

    # 無線
    spans = busy_spans(obs, t1)
    busy = lambda t: any(a - 5 <= t <= b + 5 for a, b in spans)
    L += ["## 無線", "", "| ODU | 受信電力 平常時の中央値 (最小) | 全負荷中の中央値 | 再接続 |", "|---|---|---|---|"]
    for ip, label, _, _ in ODUS:
        sub = [r for r in odu if r["odu"] == ip]
        idle = [num(r["signal_dbm"]) for r in sub if not busy(num(r["time"]))]
        load = [num(r["signal_dbm"]) for r in sub if busy(num(r["time"]))]
        cs = [num(r["connected_s"]) for r in sub if r.get("connected_s")]
        re_assoc = sum(b < a for a, b in zip(cs, cs[1:]))
        disc = sum(r["connected"] != "1" for r in sub)
        L.append(f"| {label.split()[0]} | {median(idle):.0f} dBm ({min(idle) if idle else float('nan'):.0f}) | "
                 f"{median(load):.0f} dBm | {re_assoc} 回" + (f"、未接続 {disc} 回" if disc else "") + " |")
        if re_assoc or disc:
            warn.append(f"{label.split()[0]} で無線の切断 (再接続 {re_assoc} 回、未接続 {disc} 回)")
    L.append("")
    for ip, name in (("192.168.1.31", "無線1"), ("192.168.1.33", "無線2")):
        m = Counter(r["tx_mcs"] for r in odu if r["odu"] == ip and r["tx_mcs"])
        tot = sum(m.values())
        L.append(f"- {name} の送信 MCS: " + ", ".join(f"{k}: {pct(v, tot)}" for k, v in sorted(m.items(), key=lambda kv: -num(kv[0]))))
    L.append("")

    # 制御
    ap_ = [num(r["applied_mbps"]) for r in ctl]
    w0 = sum(r["w1"] == "0" for r in ctl)
    acts = Counter(r["action"].split("(")[0] for r in ctl)
    L += ["## 制御", "",
          f"- CR1 の整形レート: {min(ap_):.0f}〜{max(ap_):.0f} Mbps (中央値 {median(ap_):.0f})" if ap_ else "- 制御: 記録なし",
          f"- 下げた {acts.get('down', 0)} 回 / 上げた {acts.get('up', 0)} 回 / 無線断で CR1 を外した {acts.get('link_down', 0)} 回"
          + (f" (重み 0 の記録 {w0} 回 ≒ {w0 * 2 / 60:.0f} 分)" if w0 else ""), ""]
    if acts.get("link_down") or w0:
        warn.append("無線断で CR1 を経路から外した")

    # 全負荷計測
    if summary:
        g = {k: [s[f"{k}_gbps"] for s in summary if s[f"{k}_gbps"] == s[f"{k}_gbps"]] for k, _, _ in CLASSES}
        lo = {k: [s[f"{k}_loss_pct"] for s in summary if s[f"{k}_loss_pct"] == s[f"{k}_loss_pct"]] for k, _, _ in CLASSES}
        L += ["## 全負荷計測", "", "| クラス | 受信量 最小〜最大 [Gbps] | 損失率 最大 |", "|---|---|---|"]
        for k, label, _ in CLASSES:
            if g[k]:
                L.append(f"| {label} | {min(g[k]):.3f}〜{max(g[k]):.3f} | {max(lo[k]):.4f}% |")
        L += ["", "- 理由: " + ", ".join(f"{k} {v}" for k, v in Counter(s["reason"] for s in summary).items())
              + f" / 途中で制御の値が変わった回 {sum(s['changed'] == 1 for s in summary)}", ""]
        if g["af41"] and (min(g["af41"]) < 7.9 or max(lo["af41"]) > 0.1):
            warn.append(f"AF41 が守られていない回がある (最小 {min(g['af41']):.3f} Gbps、損失 最大 {max(lo['af41']):.3f}%)")

    # ping (全負荷計測の時間帯を除く)
    pi = [r for r in ping if not busy(num(r["time"]))]
    ok = sorted(num(r["rtt_ms"]) for r in pi if r["status"] == "ok")
    bad = len(pi) - len(ok)
    L += ["## 無線区間の ping (全負荷計測の時間帯を除く)", "",
          f"- 応答なし・届かず {bad}/{len(pi)} 回 ({pct(bad, len(pi))})、往復遅延 中央値 {median(ok):.2f} ms・"
          f"上位 1% {ok[int(0.99 * (len(ok) - 1))] if ok else float('nan'):.2f} ms", ""]
    if bad:
        warn.append(f"平常時に ping の応答なし {bad} 回")

    L = L[:4] + ["## 注意すべき点", ""] + ([f"- {w}" for w in warn] or ["- なし"]) + [""] + L[4:]
    return "\n".join(L), warn


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="観測フォルダ (結果語を省いた名前でもよい)")
    ap.add_argument("--from", dest="t_from", default=None, help="図の始まり (日本時間 2026-10-03T06:00)")
    ap.add_argument("--to", dest="t_to", default=None, help="図の終わり (日本時間)")
    ap.add_argument("--report", type=float, default=None, metavar="時間",
                    help="直近 N 時間の途中経過の報告書を reports/ に作る (全期間の表と図は作らない)")
    a = ap.parse_args()
    obs = result_dir(a.dir)
    t_from = jst_epoch(a.t_from) if a.t_from else None
    t_to = jst_epoch(a.t_to) if a.t_to else None
    if a.report:
        import time as _time
        t_to = t_to or _time.time()
        t_from = t_to - a.report * 3600
    sel = lambda data: [r for r in data if (t_from is None or num(r["time"]) >= t_from)
                        and (t_to is None or num(r["time"]) <= t_to)]
    ctl = sel(rows(obs, "controller.csv"))
    odu = sel(rows(obs, "odu_*.csv"))
    ping = sel(rows(obs, "ping_*.csv"))
    wx, nc = rows(obs, "weather_*.csv"), rows(obs, "nowcast_*.csv")
    summary = [s for s in probe_rows(obs, ctl, odu, ping, wx, nc)
               if (t_from is None or jst_epoch(s["start_jst"].replace(" ", "T")) >= t_from)
               and (t_to is None or jst_epoch(s["start_jst"].replace(" ", "T")) <= t_to)]

    out_dir = obs / "summary"
    try:
        out_dir.mkdir(exist_ok=True)
        (out_dir / ".write_test").touch()
        (out_dir / ".write_test").unlink()
    except PermissionError:
        sys.exit(f"[NG] {out_dir} に書けません。観測中のフォルダは root の持ち物なので、sudo を付けて実行してください")
    if a.report:
        rep_dir = out_dir / "reports"
        rep_dir.mkdir(exist_ok=True)
        text, warn = build_report(obs, t_from, t_to, ctl, odu, ping, wx, nc, summary)
        stem = rep_dir / ("report_" + dt.datetime.fromtimestamp(t_to, JST).strftime("%Y%m%d_%H%M"))
        stem.with_suffix(".md").write_text(text)
        (out_dir / "latest_report.md").write_text(text)
        plot(obs, stem, ctl, odu, ping, wx, nc, summary, t_from, t_to)
        stem.with_suffix(".pdf").unlink(missing_ok=True)       # 報告には PNG だけ残す
        uid, gid = os.environ.get("SUDO_UID"), os.environ.get("SUDO_GID")
        if uid and gid:
            for p in [out_dir, rep_dir, *rep_dir.iterdir(), out_dir / "latest_report.md"]:
                os.chown(p, int(uid), int(gid))
        print(f"報告書: {stem.with_suffix('.md')} (注意すべき点 {len(warn)} 件)")
        return 0
    if summary:
        with (out_dir / "probes_summary.csv").open("w", newline="") as fp:
            w = csv.DictWriter(fp, fieldnames=list(summary[0]))
            w.writeheader()
            w.writerows(summary)
    plot(obs, out_dir / "timeline", ctl, odu, ping, wx, nc, summary, t_from, t_to)
    uid, gid = os.environ.get("SUDO_UID"), os.environ.get("SUDO_GID")
    if uid and gid:                      # sudo で作ったものは、ふだんのユーザーの持ち物にする
        for p in [out_dir, *out_dir.iterdir()]:
            os.chown(p, int(uid), int(gid))
    print(f"全負荷計測 {len(summary)} 回 / ODU {len(odu)} 行 / ping {len(ping)} 行 / 気象 {len(wx)} 行 / ナウキャスト {len(nc)} 行")
    print(f"出力: {out_dir}/probes_summary.csv, timeline.pdf, timeline.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
