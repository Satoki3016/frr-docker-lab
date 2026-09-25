#!/usr/bin/env python3
"""
plot_guarantee_split.py — Consideration スライド用の帯域配分図

「保証帯域は優先度と無関係に先に配られ、SPは残り（借用分）しか支配できない」を
横棒2本で図解する。スライド左列の文の視覚化であり、新しい実験条件は導入しない。

数値は C=9 Gbps 基準:
  フルシェア保証: 0.9 + 2.571 + 1.286 = 4.76 G → 借用 4.24 G → AF41上限 5.1 G
  保証 ≤10 %    : 0.9 + 0.257 + 0.129 = 1.29 G → 借用 7.71 G → AF41は 8 G 到達

使い方:
    python3 plot_guarantee_split.py [--lang en|ja]
"""
import argparse
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt

BASE = Path(__file__).resolve().parent.parent
OUT_TAG = "qos/c2/20260721_c2_sp_enabled"

C = 9.0
G_FULL, G_SMALL = 4.76, 1.29

COLOR_GUAR = "#9A9A9A"
COLOR_BORR = "#418BBF"

_TXT = {
    "en": {
        "row_full": "Full-share\nguarantees",
        "row_small": "≤10 %\n(this work)",
        "seg_guar": "Guaranteed {v:.1f} G",
        "seg_guar_s": "{v:.1f} G",
        "seg_borr": "SP governs {v:.1f} G",
        "verdict_full": "→ little left for SP to govern",
        "verdict_small": "→ SP governs most of the link",
        "xlabel": "Link capacity (Gbps)",
        "leg_guar": "Guaranteed — handed out ignoring priority",
        "leg_borr": "Borrowed — SP governs",
    },
    "ja": {
        "row_full": "フルシェア保証",
        "row_small": "保証 ≤10 %\n(本研究)",
        "seg_guar": "保証 {v:.1f} G",
        "seg_guar_s": "{v:.1f} G",
        "seg_borr": "SPが支配 {v:.1f} G",
        "verdict_full": "→ SPが支配できる分がわずか",
        "verdict_small": "→ SPがリンクの大半を支配",
        "xlabel": "リンク容量 (Gbps)",
        "leg_guar": "保証 — 優先度と無関係に配布",
        "leg_borr": "借用 — SPが支配",
    },
}


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
        "axes.spines.left": False,
        "font.size": 18, "axes.labelsize": 18,
        "xtick.labelsize": 18, "ytick.labelsize": 18, "legend.fontsize": 16,
    })

    fig, ax = plt.subplots(figsize=(11.0, 3.4))
    fig.subplots_adjust(left=0.155, right=0.985, top=0.86, bottom=0.22)

    h = 0.46
    rows = [
        (1.35, G_FULL, T["row_full"], T["verdict_full"]),
        (0.25, G_SMALL, T["row_small"], T["verdict_small"]),
    ]
    for y, g, _label, verdict in rows:
        b = C - g
        ax.barh(y, g, h, left=0, color=COLOR_GUAR, zorder=3)
        ax.barh(y, b, h, left=g, color=COLOR_BORR, zorder=3)
        seg = T["seg_guar"] if g > 2 else T["seg_guar_s"]
        ax.text(g / 2, y, seg.format(v=g), ha="center", va="center",
                fontsize=16, fontweight="bold", color="white", zorder=5)
        ax.text(g + b / 2, y, T["seg_borr"].format(v=b), ha="center", va="center",
                fontsize=16, fontweight="bold", color="white", zorder=5)
        ax.text(0, y - h / 2 - 0.12, verdict, ha="left", va="top",
                fontsize=16, fontweight="bold", color="#1c1c1c")

    ax.set_yticks([r[0] for r in rows])
    ax.set_yticklabels([r[2] for r in rows])
    ax.set_ylim(-0.55, 2.15)
    ax.set_xlim(0, C)
    ax.set_xlabel(T["xlabel"])
    ax.tick_params(axis="y", length=0)

    handles = [plt.Rectangle((0, 0), 1, 1, color=COLOR_GUAR),
               plt.Rectangle((0, 0), 1, 1, color=COLOR_BORR)]
    fig.legend(handles, [T["leg_guar"], T["leg_borr"]],
               loc="upper center", bbox_to_anchor=(0.5, 1.0), ncol=2, frameon=False)

    outdir = Path(args.outdir) if args.outdir else BASE / OUT_TAG / args.lang
    outdir.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf"):
        p = outdir / f"guarantee_split.{ext}"
        fig.savefig(p, dpi=300)
        print(f"[*] {p}")


if __name__ == "__main__":
    main()
