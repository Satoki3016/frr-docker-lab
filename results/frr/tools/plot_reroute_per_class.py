#!/usr/bin/env python3
"""
plot_reroute_per_class.py — 自動迂回の効果をクラス別に示す図

本発表の問い「輻輳中にリンクが落ちたとき、最優先クラスは再収束を生き延びるか」
に直接答える図。AF41/AF42/AF43 それぞれの通信断継続時間を、迂回なし／自動迂回で
比較する。3クラスがほぼ同一の断時間を示すことから、再収束中の断は「QoSの断」では
なく「接続性の断」であり、優先制御では短縮できない（＝検知の高速化が必要）ことが
読み取れる。

断の定義は plot_owd_transient.py と同一（OWD プローブの受信途絶 > GAP_THRESHOLD）。

ノイズ床について:
  SP 有効時の AF42/AF43 はプローブ自体が輻輳で大量に失われるため、障害が無くても
  受信間隔が開く。障害なし (frr_normal) シナリオでの最大受信間隔を「ノイズ床」として
  併記し、迂回時の断時間がそれと分離できているかを読者が判断できるようにする。

使い方:
    python3 plot_reroute_per_class.py [--tag TAG] [--lang en|ja] [--outdir DIR]
"""
import argparse
import re
from pathlib import Path
from result_paths import result_dir

import matplotlib
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np

BASE = Path(__file__).resolve().parent.parent

# 断とみなす受信途絶のしきい値 [s]（plot_owd_transient.py と同一）
GAP_THRESHOLD = 0.15

# 障害注入区間 [s]。ノイズ床もこの窓で評価し、条件を揃える。
WIN_LO, WIN_HI = 18.0, 45.0

DEFAULT_TAG = "qos/c2/20260721_c2_sp_enabled"

CLASSES = ["af41", "af42", "af43"]
CLASS_LABELS = ["High", "Medium", "Low"]

COLOR_NOREROUTE = "#DC4748"
COLOR_REROUTE = "#418BBF"
COLOR_FLOOR = "#9A9A9A"

# OSPF dead-interval [s]（迂回時間の下限）
DEAD_INTERVAL = 3.0

_TS_RE = re.compile(r'\[([0-9]+\.[0-9]+)\]\s+seq=\d+\s+owd=([0-9.-]+)\s*ms')

_TXT = {
    "en": {
        "ylabel": "Outage duration (s)",
        "xlabel": "Traffic class",
        "leg_no": "Failure (no reroute)",
        "leg_re": "Failure (auto-reroute)",
        "leg_floor": "Largest probe gap without failure",
        "leg_dead": f"OSPF dead-interval = {DEAD_INTERVAL:.0f} s",
        "footnote": ("Outage = longest interval with no OWD probe received (probe interval 20 ms), "
                     "measured over t = {lo:.0f}–{hi:.0f} s. Grey = same statistic in the no-failure\n"
                     "scenario, i.e. the noise floor produced by congestion loss alone. "
                     "Log scale."),
    },
    "ja": {
        "ylabel": "通信断継続時間 (s)",
        "xlabel": "トラフィッククラス",
        "leg_no": "障害 (迂回なし)",
        "leg_re": "障害 (自動迂回)",
        "leg_floor": "障害なし時の最大受信間隔",
        "leg_dead": f"OSPF dead-interval = {DEAD_INTERVAL:.0f} s",
        "footnote": ("断 = OWDプローブが受信されなかった区間 (プローブ間隔 20 ms)、"
                     "t = {lo:.0f}–{hi:.0f} s で評価。灰色は障害なしシナリオでの同一統計であり、\n"
                     "輻輳によるプローブ喪失のみで生じる間隔（ノイズ床）を表す。対数軸。"),
    },
}


def load_ts(path: Path) -> np.ndarray:
    """OWD ログから受信時刻列 [s]（先頭を 0 とする相対時刻）を返す。"""
    if not path.exists():
        return np.array([])
    ts = []
    for line in path.read_text(errors="ignore").splitlines():
        m = _TS_RE.match(line)
        if m:
            ts.append(float(m.group(1)))
    if not ts:
        return np.array([])
    ts = np.array(ts)
    return ts - ts[0]


def max_gap(ts: np.ndarray, lo: float, hi: float, threshold: float = 0.0) -> float:
    """[lo, hi] 区間で開始する受信途絶のうち最長のものを返す [s]。

    threshold を与えた場合、それ以下の間隔は「断ではない」とみなし 0 を返す。
    ノイズ床の評価では threshold=0 とし、実測の最大間隔をそのまま用いる。
    """
    if len(ts) < 2:
        return 0.0
    d = np.diff(ts)
    sel = (ts[:-1] >= lo) & (ts[:-1] <= hi)
    if not sel.any():
        return 0.0
    g = float(d[sel].max())
    return g if g > threshold else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default=DEFAULT_TAG)
    ap.add_argument("--lang", default="en", choices=("en", "ja"))
    ap.add_argument("--outdir", default=None)
    args = ap.parse_args()
    T = _TXT[args.lang]

    if args.lang == "en":
        matplotlib.rcParams["font.family"] = "DejaVu Sans"
    else:
        import matplotlib.font_manager as fm
        for f in ["Noto Sans CJK JP", "TakaoPGothic", "IPAPGothic", "VL PGothic"]:
            if any(f.lower() in p.name.lower() for p in fm.fontManager.ttflist):
                matplotlib.rcParams["font.family"] = f
                break

    matplotlib.rcParams.update({
        "figure.facecolor": "white", "axes.facecolor": "white",
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.alpha": 0.25, "grid.linestyle": ":",
        "font.size": 9, "axes.labelsize": 9, "axes.titlesize": 9,
        "legend.fontsize": 8, "legend.framealpha": 0.9,
    })

    root = result_dir(args.tag)
    out_no, out_re, floor = [], [], []
    for cls in CLASSES:
        out_no.append(max_gap(load_ts(root / "frr_failure" / f"owd_{cls}.log"),
                              WIN_LO, WIN_HI, GAP_THRESHOLD))
        out_re.append(max_gap(load_ts(root / "frr_failure_reroute" / f"owd_{cls}.log"),
                              WIN_LO, WIN_HI, GAP_THRESHOLD))
        # ノイズ床はしきい値を課さず、実測の最大受信間隔をそのまま用いる
        floor.append(max_gap(load_ts(root / "frr_normal" / f"owd_{cls}.log"),
                             WIN_LO, WIN_HI))
    out_no = np.array(out_no)
    out_re = np.array(out_re)
    floor = np.array(floor)

    fig, ax = plt.subplots(figsize=(6.6, 3.7), layout="constrained")
    x = np.arange(len(CLASSES))
    width = 0.26
    y_lo, y_hi = 0.01, 400.0

    series = (
        (-width, floor, COLOR_FLOOR, T["leg_floor"]),
        (0.0, out_no, COLOR_NOREROUTE, T["leg_no"]),
        (+width, out_re, COLOR_REROUTE, T["leg_re"]),
    )
    for offset, vals, color, lab in series:
        ax.bar(x + offset, vals, width, color=color, bottom=y_lo,
               edgecolor="white", linewidth=0.6, label=lab, zorder=3)
        for xi, v in zip(x + offset, vals):
            ax.text(xi, v * 1.25, f"{v:.2f}", ha="center", va="bottom",
                    fontsize=7.6, fontweight="bold", color=color, zorder=7,
                    path_effects=[pe.withStroke(linewidth=2.4, foreground="white")])

    ax.axhline(DEAD_INTERVAL, color="0.25", linestyle="--", linewidth=1.2,
               zorder=5, label=T["leg_dead"])

    ax.set_yscale("log")
    ax.set_ylim(y_lo, y_hi)
    ax.set_xticks(x)
    ax.set_xticklabels(CLASS_LABELS)
    ax.set_xlabel(T["xlabel"])
    ax.set_ylabel(T["ylabel"])
    ax.legend(loc="upper center", ncol=2, fontsize=7.4)

    fig.text(0.0, -0.10, T["footnote"].format(lo=WIN_LO, hi=WIN_HI),
             fontsize=6.8, color="0.4")

    outdir = Path(args.outdir) if args.outdir else root / args.lang
    outdir.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf"):
        p = outdir / f"reroute_per_class.{ext}"
        fig.savefig(p, dpi=300, bbox_inches="tight")
        print(f"[*] {p}")

    print(f"\n--- outage duration (s) per class, {args.tag} ---")
    for lab, a, b, f in zip(["AF41", "AF42", "AF43"], out_no, out_re, floor):
        print(f"  {lab}: no-reroute={a:6.2f}  auto-reroute={b:5.2f}  "
              f"noise floor (no failure)={f:5.2f}")


if __name__ == "__main__":
    main()
