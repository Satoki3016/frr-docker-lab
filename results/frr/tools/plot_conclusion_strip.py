#!/usr/bin/env python3
"""
plot_conclusion_strip.py — 結論スライド用の状態帯（AF41 が守られていた時間）

60 秒の計測区間を「配送できていた区間」と「通信断の区間」で塗り分け、
迂回なし／自動迂回の2本を実時間軸で並べる。断の長さを数値ではなく面積で示す。

断区間は plot_owd_transient.py と同じ定義（OWD プローブの受信途絶）で抽出する。

使い方:
    python3 plot_conclusion_strip.py [--tag TAG] [--lang en|ja]
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

GAP_THRESHOLD = 0.15
DEFAULT_TAG = "qos/c2/20260721_c2_sp_enabled"
DURATION = 60.0

COLOR_UP = "#4C9F4C"
COLOR_DOWN = "#DC4748"

_TS_RE = re.compile(r'\[([0-9]+\.[0-9]+)\]\s+seq=\d+\s+owd=([0-9.-]+)\s*ms')

ROWS = [
    ("frr_failure",         "row_nore"),
    ("frr_failure_reroute", "row_re"),
]

_TXT = {
    "en": {
        "row_nore": "No reroute",
        "row_re": "Auto-reroute",
        "xlabel": "Elapsed time (s)",
        "leg_up": "High-priority traffic delivered",
        "leg_down": "High-priority traffic lost",
        "fmt": "{:.1f} s",
    },
    "ja": {
        "row_nore": "迂回なし",
        "row_re": "自動迂回",
        "xlabel": "経過時間 (s)",
        "leg_up": "高優先トラフィック到達",
        "leg_down": "高優先トラフィック断",
        "fmt": "{:.1f} s",
    },
}


def outage_interval(path: Path):
    """最長の受信途絶を (開始, 終了) で返す。無ければ None。"""
    if not path.exists():
        return None
    ts = []
    for line in path.read_text(errors="ignore").splitlines():
        m = _TS_RE.match(line)
        if m:
            ts.append(float(m.group(1)))
    if len(ts) < 2:
        return None
    ts = np.array(ts)
    ts -= ts[0]
    d = np.diff(ts)
    k = int(np.argmax(d))
    return (ts[k], ts[k + 1]) if d[k] > GAP_THRESHOLD else None


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
        "axes.spines.left": False,
        "font.size": 18, "axes.labelsize": 18,
        "xtick.labelsize": 18, "ytick.labelsize": 18, "legend.fontsize": 18,
    })

    root = result_dir(args.tag)
    fig, ax = plt.subplots(figsize=(8.4, 2.4), layout="constrained")

    h = 0.52
    for i, (scen, key) in enumerate(ROWS):
        y = len(ROWS) - 1 - i
        ax.broken_barh([(0, DURATION)], (y - h / 2, h), color=COLOR_UP, zorder=2)
        iv = outage_interval(root / scen / f"owd_af41.log")
        if iv:
            lo, hi = iv
            ax.broken_barh([(lo, hi - lo)], (y - h / 2, h), color=COLOR_DOWN, zorder=3)
            ax.text((lo + hi) / 2, y, T["fmt"].format(hi - lo), ha="center", va="center",
                    fontsize=17, fontweight="bold", color="white", zorder=5,
                    path_effects=[pe.withStroke(linewidth=2.2, foreground=COLOR_DOWN)])

    ax.set_yticks(range(len(ROWS)))
    ax.set_yticklabels([T[k] for _, k in ROWS][::-1])
    ax.set_ylim(-0.55, len(ROWS) + 0.55)
    ax.set_xlim(0, DURATION)
    ax.set_xlabel(T["xlabel"])
    ax.tick_params(axis="y", length=0)

    handles = [plt.Rectangle((0, 0), 1, 1, color=COLOR_UP),
               plt.Rectangle((0, 0), 1, 1, color=COLOR_DOWN)]
    ax.legend(handles, [T["leg_up"], T["leg_down"]],
              loc="upper center", ncol=2, frameon=False)

    outdir = Path(args.outdir) if args.outdir else root / args.lang
    outdir.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf"):
        p = outdir / f"conclusion_strip.{ext}"
        fig.savefig(p, dpi=300)
        print(f"[*] {p}")


if __name__ == "__main__":
    main()
