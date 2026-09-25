#!/usr/bin/env python3
"""
plot_outage_conditions.py — 自動迂回時の断継続時間が条件に依らないことを示す図

考察スライド用。実機(C2)/仮想(veth) × SP有効/無効 の4条件で、自動迂回時の
AF41 断継続時間を並べる。いずれも OSPF dead-interval (3 s) の直下に揃うことから、
断は優先制御ではなく障害検知で決まっていることが読み取れる。

断の定義は plot_owd_transient.py と同一（OWD プローブの受信途絶）。

使い方:
    python3 plot_outage_conditions.py [--lang en|ja] [--outdir DIR]
"""
import argparse
import re
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

BASE = Path(__file__).resolve().parent.parent

GAP_THRESHOLD = 0.15
DEAD_INTERVAL = 3.0
SCENARIO = "frr_failure_reroute"

CONDITIONS = [
    ("qos/c2/20260721_c2_sp_enabled",     "c2_on"),
    ("qos/c2/20260721_c2_sp_uniform",     "c2_off"),
    ("qos/veth/20260721_veth9G_sp_enabled", "veth_on"),
    ("qos/veth/20260721_veth9G_sp_uniform", "veth_off"),
]

COLOR = "#418BBF"

_TS_RE = re.compile(r'\[([0-9]+\.[0-9]+)\]\s+seq=\d+\s+owd=([0-9.-]+)\s*ms')

_TXT = {
    "en": {
        "c2_on": "Physical\nSP on", "c2_off": "Physical\nSP off",
        "veth_on": "Virtual\nSP on", "veth_off": "Virtual\nSP off",
        "ylabel": "Outage duration (s)",
        "dead": f"OSPF dead-interval = {DEAD_INTERVAL:.0f} s",
        "footnote": "High-priority traffic, failure with auto-reroute. Outage = interval with no OWD probe received.",
    },
    "ja": {
        "c2_on": "実機\nSP有効", "c2_off": "実機\nSP無効",
        "veth_on": "仮想\nSP有効", "veth_off": "仮想\nSP無効",
        "ylabel": "通信断継続時間 (s)",
        "dead": f"OSPF dead-interval = {DEAD_INTERVAL:.0f} s",
        "footnote": "高優先トラフィック、自動迂回あり。断 = OWDプローブが受信されなかった区間。",
    },
}


def outage(path: Path) -> float:
    """最長の受信途絶を秒で返す。"""
    if not path.exists():
        return 0.0
    ts = [float(m.group(1)) for m in
          (_TS_RE.match(l) for l in path.read_text(errors="ignore").splitlines()) if m]
    if len(ts) < 2:
        return 0.0
    d = np.diff(np.array(ts))
    return float(d.max()) if d.max() > GAP_THRESHOLD else 0.0


def main():
    ap = argparse.ArgumentParser()
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
        "font.size": 9.5, "axes.labelsize": 9.5, "legend.fontsize": 8.5,
    })

    vals = [outage(BASE / tag / SCENARIO / "owd_af41.log") for tag, _ in CONDITIONS]
    labels = [T[key] for _, key in CONDITIONS]

    fig, ax = plt.subplots(figsize=(5.4, 2.6), layout="constrained")
    x = np.arange(len(vals))
    ax.bar(x, vals, 0.5, color=COLOR, edgecolor="white", linewidth=0.6, zorder=3)
    for xi, v in zip(x, vals):
        ax.text(xi, v + 0.09, f"{v:.2f}", ha="center", va="bottom",
                fontsize=9, fontweight="bold", color=COLOR, zorder=5)

    ax.axhline(DEAD_INTERVAL, color="0.25", linestyle="--", linewidth=1.2,
               zorder=4, label=T["dead"])
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel(T["ylabel"])
    ax.set_ylim(0, 4.0)
    ax.legend(loc="upper right")

    fig.text(0.0, -0.09, T["footnote"], fontsize=6.8, color="0.4")

    outdir = Path(args.outdir) if args.outdir else BASE / CONDITIONS[0][0] / args.lang
    outdir.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf"):
        p = outdir / f"outage_conditions.{ext}"
        fig.savefig(p, dpi=300, bbox_inches="tight")
        print(f"[*] {p}")

    print("\n--- auto-reroute outage (s) ---")
    for (tag, _), v in zip(CONDITIONS, vals):
        print(f"  {tag:32s} {v:.3f}")


if __name__ == "__main__":
    main()
