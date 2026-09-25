#!/usr/bin/env python3
"""ECMP と容量比WCMP の比較図 (normal シナリオ)。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from result_paths import result_dir  # noqa: E402
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.font_manager as fm
import numpy as np

for _f in ["Noto Sans CJK JP", "TakaoPGothic", "IPAPGothic"]:
    if any(_f.lower() in p.name.lower() for p in fm.fontManager.ttflist):
        matplotlib.rcParams["font.family"] = _f; break
matplotlib.rcParams.update({
    "figure.facecolor":"white","axes.facecolor":"white",
    "axes.spines.top":False,"axes.spines.right":False,"axes.linewidth":0.8,
    "axes.labelsize":9,"axes.titlesize":9,"axes.titlepad":4,
    "xtick.labelsize":8,"ytick.labelsize":8,"legend.fontsize":8,
    "xtick.major.width":0.8,"ytick.major.width":0.8,
    "legend.framealpha":0.95,"legend.edgecolor":"0.8"})

# (条件, AF41, AF42, AF43, CR1, CR2, CR3, CR1容量)
D = [("ECMP\n無線 0.9G", 6.268, 5.181, 5.294, 0.900, 7.424, 8.430, 0.9),
     ("WCMP\n無線 0.9G", 8.048, 7.228, 3.614, 0.900, 9.000, 9.000, 0.9),
     ("ECMP\n無線 2.16G", 7.845, 5.846, 4.876, 2.160, 9.000, 7.424, 2.16),
     ("WCMP\n無線 2.16G", 8.045, 6.875, 5.223, 2.160, 9.000, 9.000, 2.16)]

lab = [d[0] for d in D]
x = np.arange(len(D)); w = 0.26
C = ["#0072B2", "#E69F00", "#CC79A7"]

fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.4, 3.2))

for i, (nm, c) in enumerate(zip(["AF41 (高)", "AF42 (中)", "AF43 (低)"], C)):
    v = [d[1+i] for d in D]
    b = a1.bar(x + (i-1)*w, v, w, color=c, label=nm, zorder=3)
    a1.bar_label(b, fmt="%.2f", fontsize=6.4, padding=1.5)
a1.set_ylabel("スループット [Gbps]"); a1.set_ylim(0, 9.6)
a1.set_xticks(x); a1.set_xticklabels(lab)
a1.grid(axis="y", lw=0.4, color="0.9", zorder=0)
a1.legend(loc="upper left", ncol=3, columnspacing=0.8, handlelength=1.2)
a1.set_title("(a) クラス別スループット", loc="left", fontweight="bold")

for i, (nm, c) in enumerate(zip(["CR1 (無線)", "CR2 (有線)", "CR3 (有線)"],
                                ["#D55E00", "#009E73", "#56B4E9"])):
    cap = [d[7] if i == 0 else 9.0 for d in D]
    v = [d[4+i]/cp*100 for d, cp in zip(D, cap)]
    b = a2.bar(x + (i-1)*w, v, w, color=c, label=nm, zorder=3)
    a2.bar_label(b, fmt="%.0f", fontsize=6.4, padding=1.5)
a2.set_ylabel("リンク利用率 [%]"); a2.set_ylim(0, 128)
a2.set_yticks([0, 25, 50, 75, 100])
a2.axhline(100, lw=0.7, color="#B03A2E", ls="--", zorder=2)
a2.set_xticks(x); a2.set_xticklabels(lab)
a2.grid(axis="y", lw=0.4, color="0.9", zorder=0)
a2.legend(loc="upper left", ncol=3, columnspacing=0.8, handlelength=1.2)
a2.set_title("(b) 各経路の容量利用率", loc="left", fontweight="bold")

fig.tight_layout()
out = str(result_dir("20260918_success_dynamic_control") / "ecmp_vs_wcmp")
fig.savefig(out + ".pdf", bbox_inches="tight")
fig.savefig(out + ".png", dpi=300, bbox_inches="tight")
print("出力:", out + ".pdf / .png")
