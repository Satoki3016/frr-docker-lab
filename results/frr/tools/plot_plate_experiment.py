#!/usr/bin/env python3
"""金属板の障害実験 (2026-10-12、実機 c2) の図を作る。

    python3 results/frr/tools/plot_plate_experiment.py --dir 20261012_rainobs_04

1 枚に 1 つの量 (横軸は時間、縦軸はその量の単位、凡例は図の中)。代表の回は、各条件の金属板の
3 回のうち AF41 の損失率が中央値の回。
    fig1_mcs            無線 1 の送信 MCS (P4・S・N の 3 回を重ねる)
    fig2_af41_throughput AF41 の受信スループット (P4・S・N)
    fig3_class_throughput 3 クラスの受信スループット (P4)
    fig4_owd             3 クラスの片方向遅延 (P4)
    fig5_af41_loss       AF41 の損失率 (全条件・全回。横軸は条件)

時刻の基準は、各回の timebase.txt (受信スループットの記録の t=0)。fault コマンドの
「置く」「外す」の合図も同じ t=0 から 20 秒・50 秒に出している。
"""
from __future__ import annotations

import argparse
import csv
import re
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.font_manager as fm  # noqa: E402
import radwin_obs_layout as lay  # noqa: E402
import summarize_rain_observation as sm  # noqa: E402

for _f in ["Noto Sans CJK JP", "TakaoPGothic", "IPAPGothic"]:
    if any(_f.lower() in p.name.lower() for p in fm.fontManager.ttflist):
        matplotlib.rcParams["font.family"] = _f
        break
matplotlib.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white",
    "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 0.8,
    "axes.labelsize": 9, "axes.titlesize": 9, "axes.titlepad": 4, "axes.labelpad": 3,
    "xtick.labelsize": 8, "ytick.labelsize": 8, "legend.fontsize": 7.5,
    "xtick.major.width": 0.8, "ytick.major.width": 0.8,
    "legend.framealpha": 0.95, "legend.edgecolor": "0.8"})

CLS = [("af41", "AF41 (高)", "#0072B2"), ("af42", "AF42 (中)", "#E69F00"), ("af43", "AF43 (低)", "#CC79A7")]
HOP = [("192.168.1.31", "無線 1 (.31→.32)", "#009E73", "-"), ("192.168.1.33", "無線 2 (.33→.34)", "#D55E00", "--")]
CONDS = [("P", "P"), ("P3", "P3"), ("P4", "P4"), ("S", "S"), ("N", "N")]
PLATE_ON, PLATE_OFF = 20, 50          # fault --duration 30 の合図 (通信開始から)。--plate-seconds で変える
LABEL = "plate30"                   # 障害ありの回の fault のラベル。--label で変える
# 遮られた区間が約 55 秒と長かったため除外し、測り直した回 (01_report/plate_experiment_20261012.md)
EXCLUDE = {"20261012_success_rainobs_wcmp_140": "S: 遮られた区間 約 52 秒・無線 2 も",
           "20261012_success_rainobs_wcmp_141": "P4: 遮られた区間 約 55 秒"}


def load_runs(obs: Path) -> list[dict]:
    runs = []
    for p in csv.DictReader((lay.sub(obs, lay.FULLLOAD) / "probes.csv").open()):
        m = re.fullmatch(rf"fault:(none|{re.escape(LABEL)})@(P|P3|P4|S|N)", p["reason"])
        if not m or p["folder"] in EXCLUDE:
            continue
        d = lay.probe_dir(obs, p["folder"]) / "frr_observe"
        t0 = int(re.search(r"throughput_t0_epoch_ms=(\d+)", (d / "timebase.txt").read_text()).group(1)) / 1000
        runs.append({"folder": p["folder"], "state": "none" if m.group(1) == "none" else "fault",
                     "cond": m.group(2), "dir": d, "t0": t0,
                     "loss": sm.iperf_loss_pct(d / "iperf3_af41.log")})
    return runs


def throughput(d: Path) -> tuple[list[int], dict[str, list[float]]]:
    rows = list(csv.DictReader((d / "throughput.csv").open()))
    t = [int(r["time"]) for r in rows]
    return t, {k: [float(r[f"rx{i}_bytes_per_sec"]) * 8 / 1e9 for r in rows]
               for i, (k, _, _) in enumerate(CLS, start=1)}


def owd(d: Path, cls: str, t0: float) -> list[tuple[float, float]]:
    text = (d / f"owd_{cls}.log").read_text(errors="replace")
    return [(float(m.group(1)) - t0, float(m.group(2)))
            for m in re.finditer(r"^\[([\d.]+)\] seq=\d+ owd=([\d.]+) ms", text, re.M)]


def per_second(points: list[tuple[float, float]], fn) -> tuple[list[int], list[float]]:
    b: dict[int, list[float]] = {}
    for t, v in points:
        b.setdefault(int(t), []).append(v)
    ks = sorted(b)
    return ks, [fn(b[k]) for k in ks]


def mcs_series(odu: list[dict], ip: str, t0: float) -> tuple[list[float], list[float]]:
    pts = sorted((float(r["time"]) - t0, (float(r["tx_mcs"]) if r["connected"] == "1" and r["tx_mcs"] else 0.0))
                 for r in odu if r["odu"] == ip and -5 <= float(r["time"]) - t0 <= 125)
    return [p[0] for p in pts], [p[1] for p in pts]


def shade(ax):
    ax.axvspan(PLATE_ON, PLATE_OFF, color="#EDEDED", zorder=0, lw=0)


def representative(runs: list[dict], cond: str) -> dict:
    """その条件の金属板の回のうち、AF41 損失率が中央値の回。"""
    g = sorted((r for r in runs if r["cond"] == cond and r["state"] == "fault"), key=lambda r: r["loss"])
    return g[len(g) // 2]


COND_STYLE = {"P4": ("P4 (改良+待つ)", "#0072B2", "-"), "S": ("S (動的制御なし)", "#E69F00", "--"),
              "N": ("N (迂回も動的制御もなし)", "#D55E00", ":")}


def _single(xlabel: str, ylabel: str):
    fig, ax = plt.subplots(figsize=(5.0, 2.9))
    shade(ax)
    ax.text((PLATE_ON + PLATE_OFF) / 2, 1.0, "金属板", transform=ax.get_xaxis_transform(),
            ha="center", va="bottom", fontsize=8, color="0.3")
    ax.grid(axis="y", lw=0.4, color="0.9", zorder=0)
    ax.set_xlim(0, 120)
    ax.set_xticks(range(0, 121, 20))
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    return fig, ax


def _save(fig, path: Path) -> None:
    fig.savefig(path.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(path.with_suffix(".png"), dpi=300, bbox_inches="tight")
    plt.close(fig)


def _trim(t, *series):
    keep = [i for i, tt in enumerate(t) if 4 <= tt <= 118]       # 通信の立ち上がり (約 3 秒) と終わりの 2 秒は除く
    return [t[i] for i in keep], *[[v[i] for i in keep] for v in series]


def simple_figures(runs: list[dict], odu: list[dict], out: Path) -> None:
    reps = {c: representative(runs, c) for c in COND_STYLE}
    X = "時間 [s]"
    # 1. MCS
    fig, ax = _single(X, "無線 1 の送信 MCS")
    for c, (lab, col, ls) in COND_STYLE.items():
        x, y = mcs_series(odu, HOP[0][0], reps[c]["t0"])
        ax.step(x, y, where="post", color=col, ls=ls, lw=1.6, label=lab)
    ax.set_ylim(-0.5, 12.8)
    ax.set_yticks([0, 3, 6, 9, 12])
    ax.legend(loc="lower right", fontsize=8)
    _save(fig, out / "fig1_mcs")
    # 2. AF41 のスループット
    fig, ax = _single(X, "AF41 受信スループット [Gbit/s]")
    for c, (lab, col, ls) in COND_STYLE.items():
        t, thr = throughput(reps[c]["dir"])
        t, y = _trim(t, thr["af41"])
        ax.plot(t, y, color=col, ls=ls, lw=1.4, label=f"{lab}  損失率 {reps[c]['loss']:.2f}%")
    ax.set_ylim(6.9, 8.25)
    ax.legend(loc="lower right", fontsize=8)
    _save(fig, out / "fig2_af41_throughput")
    # 3. 3 クラスのスループット (P4)
    fig, ax = _single(X, "受信スループット [Gbit/s]")
    t, thr = throughput(reps["P4"]["dir"])
    for k, lab, col in CLS:
        tt, y = _trim(t, thr[k])
        ax.plot(tt, y, color=col, lw=1.4, label=lab)
    ax.set_ylim(0, 9)
    ax.legend(loc="lower right", fontsize=8, title="P4 (改良+待つ)", title_fontsize=8)
    _save(fig, out / "fig3_class_throughput")
    # 4. 片方向遅延 (P4)
    fig, ax = _single(X, "片方向遅延 [ms]")
    for k, lab, col in CLS:
        pts = [(x, v) for x, v in owd(reps["P4"]["dir"], k, reps["P4"]["t0"]) if 2 <= x <= 118]
        xs, med = per_second(pts, st.median)
        ax.plot(xs, med, color=col, lw=1.4, label=lab)
    ax.set_yscale("log")
    ax.set_ylim(0.05, 1000)
    ax.legend(loc="lower right", bbox_to_anchor=(1.0, 0.16), fontsize=8, ncol=3, columnspacing=0.8,
              title="P4 (改良+待つ)、1 秒ごとの中央値", title_fontsize=7.5)
    _save(fig, out / "fig4_owd")
    # 5. AF41 の損失率 (全条件・全回)
    fig, ax = plt.subplots(figsize=(5.0, 2.9))
    xs = {c: i for i, (c, _) in enumerate(CONDS)}
    for state, dx, face, lab in (("none", -0.15, "white", "障害なし"), ("fault", 0.15, "#333333", f"金属板 {PLATE_OFF - PLATE_ON} 秒")):
        first = True
        for c, _ in CONDS:
            g = [r for r in runs if r["cond"] == c and r["state"] == state]
            for k, r in enumerate(g):
                ax.plot(xs[c] + dx + (k - 1) * 0.05, r["loss"], "o", ms=5, mfc=face, mec="#333333", mew=0.9,
                        label=lab if first else None)
                first = False
    ax.set_yscale("log")
    ax.set_ylim(1e-3, 5)
    ax.set_xticks(range(len(CONDS)))
    ax.set_xticklabels(["P\n今の方式", "P3\n改良", "P4\n改良+待つ", "S\n制御なし", "N\n迂回も\n制御もなし"], fontsize=8)
    ax.set_xlim(-0.6, len(CONDS) - 0.4)
    ax.set_ylabel("AF41 損失率 [%]")
    ax.grid(axis="y", lw=0.4, color="0.9")
    ax.legend(loc="upper left", fontsize=8)
    _save(fig, out / "fig5_af41_loss")


# ── 論文 (PN 研究会) 用: 論文中の用語だけを使う ─────────────────────────
PAPER_COND = {"P": ("動的制御あり", "#0072B2", "-"), "S": ("動的制御なし", "#E69F00", "--"),
              "N": ("動的制御・経路監視なし", "#D55E00", ":")}
PAPER_CLS = [("af41", "AF41", "#0072B2"), ("af42", "AF42", "#E69F00"), ("af43", "AF43", "#CC79A7")]


def _paper_axes(ylabel: str):
    fig, ax = plt.subplots(figsize=(3.4, 2.25))
    ax.axvspan(PLATE_ON, PLATE_OFF, color="#E6E6E6", zorder=0, lw=0)
    ax.text((PLATE_ON + PLATE_OFF) / 2, 1.01, "遮蔽操作", transform=ax.get_xaxis_transform(),
            ha="center", va="bottom", fontsize=7)
    ax.grid(axis="y", lw=0.4, color="0.88", zorder=0)
    ax.set_xlim(0, 120)
    ax.set_xticks(range(0, 121, 20))
    ax.set_xlabel("経過時間 [s]", fontsize=8)
    ax.set_ylabel(ylabel, fontsize=8)
    ax.tick_params(labelsize=7.5)
    return fig, ax


def paper_figures(runs: list[dict], odu: list[dict], out: Path) -> dict:
    reps = {c: representative(runs, c) for c in PAPER_COND}
    # MCS (無線第 1 ホップ)
    fig, ax = _paper_axes("第1ホップのMCS")
    for c, (lab, col, ls) in PAPER_COND.items():
        x, y = mcs_series(odu, HOP[0][0], reps[c]["t0"])
        ax.step(x, y, where="post", color=col, ls=ls, lw=1.4, label=lab)
    ax.set_ylim(-0.5, 12.8)
    ax.set_yticks([0, 3, 6, 9, 12])
    ax.legend(loc="center right", bbox_to_anchor=(1.0, 0.45), fontsize=6.5, handlelength=2.2)
    _save(fig, out / "pn_mcs")
    # AF41 の受信レート
    fig, ax = _paper_axes("AF41受信レート [Gbps]")
    for c, (lab, col, ls) in PAPER_COND.items():
        t, thr = throughput(reps[c]["dir"])
        t, y = _trim(t, thr["af41"])
        ax.plot(t, y, color=col, ls=ls, lw=1.2, label=lab)
    ax.set_ylim(6.9, 8.25)
    ax.legend(loc="lower right", fontsize=6.5, handlelength=2.2, borderaxespad=0.3)
    _save(fig, out / "pn_af41_rate")
    # 3 クラスの受信レート (動的制御あり)
    fig, ax = _paper_axes("受信レート [Gbps]")
    t, thr = throughput(reps["P"]["dir"])
    for k, lab, col in PAPER_CLS:
        tt, y = _trim(t, thr[k])
        ax.plot(tt, y, color=col, lw=1.2, label=lab)
    ax.set_ylim(0, 9)
    ax.legend(loc="lower right", fontsize=6.5, ncol=3, columnspacing=0.8, handlelength=1.6, borderaxespad=0.3)
    _save(fig, out / "pn_class_rate")
    # 片方向遅延 (動的制御あり、1 秒ごとの中央値)
    fig, ax = _paper_axes("片方向遅延 [ms]")
    for k, lab, col in PAPER_CLS:
        pts = [(x, v) for x, v in owd(reps["P"]["dir"], k, reps["P"]["t0"]) if 4 <= x <= 118]
        xs, med = per_second(pts, st.median)
        ax.plot(xs, med, color=col, lw=1.2, label=lab)
    ax.set_yscale("log")
    ax.set_ylim(0.05, 1000)
    ax.legend(loc="lower right", bbox_to_anchor=(1.0, 0.18), fontsize=6.5, ncol=3, columnspacing=0.8,
              handlelength=1.6)
    _save(fig, out / "pn_owd")
    # AF41 損失率 (論文の図 2 の差し替え): 条件ごとの中央値の棒と範囲のひげ。通常の軸
    conds = [("P", "動的制御\nあり"), ("P3", "分配判定\nを追加"), ("P4", "復帰時の\n待機を追加"),
             ("S", "動的制御\nなし"), ("N", "動的制御・\n経路監視なし")]
    fig, ax = plt.subplots(figsize=(3.4, 2.45))
    w = 0.36
    for j, (state, lab, face) in enumerate((("none", "障害なし", "white"), ("fault", "障害あり", "#4D4D4D"))):
        for i, (c, _) in enumerate(conds):
            v = [r["loss"] for r in runs if r["cond"] == c and r["state"] == state]
            med = st.median(v)
            x = i + (j - 0.5) * w
            ax.bar(x, med, w, color=face, edgecolor="#333333", lw=0.8, zorder=3, label=lab if i == 0 else None)
            ax.errorbar(x, med, yerr=[[med - min(v)], [max(v) - med]], fmt="none", ecolor="#333333",
                        elinewidth=0.8, capsize=2.2, zorder=4)
            if state == "fault":
                ax.text(x, max(v) + 0.04, f"{med:.2f}", ha="center", va="bottom", fontsize=6.5)
    ax.set_xticks(range(len(conds)))
    ax.set_xticklabels([lab for _, lab in conds], fontsize=6.6)
    ax.set_ylabel("AF41損失率 [%]", fontsize=8)
    ax.set_ylim(0, 2.25)
    ax.tick_params(axis="y", labelsize=7.5)
    ax.grid(axis="y", lw=0.4, color="0.88", zorder=0)
    ax.legend(loc="upper left", fontsize=7)
    _save(fig, out / "pn_loss")
    return reps


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="観測フォルダ (例 20261012_rainobs_04)")
    ap.add_argument("--out", default=None, help="出力先フォルダ (既定: 観測フォルダの 01_report/figures)")
    ap.add_argument("--paper", action="store_true",
                    help="論文 (PN 研究会) 用の図 pn_*.pdf/png を作る (論文中の条件名・用語だけを使う、1 段組の幅)")
    ap.add_argument("--label", default="plate30", help="障害ありの回の fault のラベル (例 plate80)")
    ap.add_argument("--plate-seconds", type=int, default=30, help="金属板を置いた秒数 (fault --duration と同じ値)")
    a = ap.parse_args()
    global LABEL, PLATE_OFF
    LABEL, PLATE_OFF = a.label, PLATE_ON + a.plate_seconds
    obs = sm.resolve_dir(a.dir) if hasattr(sm, "resolve_dir") else Path(a.dir)
    runs = load_runs(obs)
    odu = sm.rows(obs, "odu*.csv")
    out = Path(a.out) if a.out else lay.sub(obs, lay.REPORT) / "figures"
    out.mkdir(parents=True, exist_ok=True)
    for old in ("plate_timeseries", "plate_summary"):            # 以前の複数段の図は消す
        for ext in (".pdf", ".png"):
            (out / (old + ext)).unlink(missing_ok=True)
    simple_figures(runs, odu, out)
    if a.paper:
        reps = paper_figures(runs, odu, out)
        print("論文用の代表:", ", ".join(f"{PAPER_COND[c][0]}={r['folder'][-3:]} ({r['loss']:.4f}%)" for c, r in reps.items()))
    n = {(r["cond"], r["state"]): 0 for r in runs}
    for r in runs:
        n[(r["cond"], r["state"])] += 1
    print("回数:", ", ".join(f"{c}/{s}={v}" for (c, s), v in sorted(n.items())))
    print("除外:", "; ".join(f"{k[-3:]} {v}" for k, v in EXCLUDE.items()))
    print("出力:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
