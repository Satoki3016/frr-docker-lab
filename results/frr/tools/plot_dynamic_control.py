#!/usr/bin/env python3
"""無線容量の変動に対する動的制御の追従を可視化する。

入力:
  --ctrl   radwin_wcmp_controller.py が出力した CSV
  --tput   iperf3 の [SUM] 行から抽出した "秒 Gbps" の2列テキスト
  --offset iperf 時刻 = コントローラ時刻 + offset [s]

上段: 実測スループット / 推定容量 / 適用したHTB整形レート
下段: 各ホップの MCS と受信信号強度
"""
from __future__ import annotations
import argparse, csv, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from result_paths import result_dir  # noqa: E402
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

for _f in ["Noto Sans CJK JP", "TakaoPGothic", "IPAPGothic", "VL PGothic"]:
    if any(_f.lower() in p.name.lower() for p in fm.fontManager.ttflist):
        matplotlib.rcParams["font.family"] = _f
        break

matplotlib.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white",
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.linewidth": 0.8, "axes.labelsize": 9, "axes.titlesize": 9,
    "axes.titlepad": 4, "axes.labelpad": 3,
    "xtick.labelsize": 8, "ytick.labelsize": 8,
    "xtick.direction": "out", "ytick.direction": "out",
    "xtick.major.size": 3, "ytick.major.size": 3,
    "xtick.major.width": 0.8, "ytick.major.width": 0.8,
    "legend.fontsize": 8, "legend.framealpha": 0.95,
    "legend.edgecolor": "0.8", "legend.borderpad": 0.4,
})

# Okabe-Ito (色覚多様性に配慮)
C_MEAS = "#333333"; C_EST = "#E69F00"; C_APP = "#0072B2"
C_H1 = "#009E73";   C_H2 = "#CC79A7"; C_SIG = "#999999"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ctrl", default="/tmp/radwin_controller.csv")
    ap.add_argument("--tput", default="/tmp/tput.txt")
    ap.add_argument("--offset", type=float, default=13.8)
    ap.add_argument("--tag", default="20260918_success_dynamic_control",
                    help="出力先の実験タグ")
    ap.add_argument("--out", default=None,
                    help="出力パスの明示指定 (省略時は --tag のフォルダ内)")
    args = ap.parse_args()
    if args.out is None:
        args.out = str(result_dir(args.tag) / "dynamic_control")

    rows = list(csv.DictReader(open(args.ctrl)))
    t0 = float(rows[0]["time"])
    t   = [float(r["time"]) - t0 for r in rows]
    est = [float(r["est_mbps"]) for r in rows]
    app = [int(r["applied_mbps"]) for r in rows]
    m1  = [int(r["hop1_mcs"]) for r in rows]
    m2  = [int(r["hop2_mcs"]) for r in rows]
    s1  = [float(r["hop1_dbm"]) if r["hop1_dbm"] else None for r in rows]
    s2  = [float(r["hop2_dbm"]) if r["hop2_dbm"] else None for r in rows]
    act = [r["action"] for r in rows]

    tp_t, tp_v = [], []
    for line in open(args.tput):
        a, b = line.split()
        tp_t.append(float(a) - args.offset)
        tp_v.append(float(b) * 1000.0)          # Gbps → Mbps

    tmax = max(t)
    keep = [i for i, x in enumerate(tp_t) if -1 <= x <= tmax + 1]
    tp_t = [tp_t[i] for i in keep]; tp_v = [tp_v[i] for i in keep]

    # 手動操作の区間 (劣化開始〜回復開始)
    deg_lo = next(t[i] for i in range(len(t)) if act[i] == "down")
    deg_hi = next(t[i] for i in range(len(t)-1, -1, -1) if est[i] < 1000) + 2.0

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(7.2, 5.4), sharex=True,
        gridspec_kw={"height_ratios": [1.45, 1.0], "hspace": 0.13})

    # ── 上段 ───────────────────────────────────────────────
    for ax in (ax1, ax2):
        ax.axvspan(deg_lo, deg_hi, color="#F0F0F0", zorder=0)
    ax1.text((deg_lo+deg_hi)/2, 1780, "手動でアンテナを操作", ha="center",
             va="center", fontsize=8, color="#777777", style="italic")

    ax1.plot(tp_t, tp_v, lw=0.9, color=C_MEAS, zorder=3,
             label="実測スループット (iperf3, 1 s平均)")
    ax1.step(t, est, where="post", lw=1.6, color=C_EST, zorder=4,
             label=r"推定容量 $\hat{C}=\min(\mathrm{PHY}_1,\mathrm{PHY}_2)\times0.52$")
    ax1.step(t, app, where="post", lw=1.4, color=C_APP, ls="--", zorder=5,
             label="制御が適用した整形レート (CR1_BW)")

    for i, a in enumerate(act):
        if a == "down":
            ax1.plot(t[i], 70, marker="v", ms=5, color="#D55E00", zorder=6,
                     clip_on=False)
        elif a == "up":
            ax1.plot(t[i], 70, marker="^", ms=5, color="#009E73", zorder=6,
                     clip_on=False)
    ax1.plot([], [], "v", color="#D55E00", ms=5, ls="none", label="down (即時)")
    ax1.plot([], [], "^", color="#009E73", ms=5, ls="none", label="up (3回連続確認後)")

    ax1.set_ylabel("レート [Mbps]")
    ax1.set_ylim(0, 3300)
    ax1.set_yticks([0, 500, 1000, 1500, 2000, 2500])
    ax1.grid(axis="y", lw=0.4, color="0.9", zorder=0)
    ax1.legend(loc="upper center", ncol=3, columnspacing=1.2,
               handlelength=1.8, borderaxespad=0.3)
    ax1.set_title("(a) 無線容量の変動に対する制御の追従", loc="left", fontweight="bold")

    # ── 下段 ───────────────────────────────────────────────
    ax2.step(t, m1, where="post", lw=1.4, color=C_H1, label="無線1 MCS")
    ax2.step(t, m2, where="post", lw=1.4, color=C_H2, label="無線2 MCS")
    ax2.set_ylabel("MCS インデックス")
    ax2.set_ylim(0, 13.5)
    ax2.set_yticks([0, 3, 6, 9, 12])
    ax2.grid(axis="y", lw=0.4, color="0.9", zorder=0)
    ax2.set_xlabel("制御ループ開始からの経過時間 [s]")

    ax3 = ax2.twinx()
    ax3.spines["top"].set_visible(False)
    ax3.spines["right"].set_visible(True)
    ax3.spines["right"].set_linewidth(0.8)
    ax3.spines["right"].set_color("#888888")
    ax3.plot(t, s1, lw=0.8, color=C_SIG, ls="-",  alpha=0.85, label="無線1 受信電力")
    ax3.plot(t, s2, lw=0.8, color=C_SIG, ls=":", alpha=0.85, label="無線2 受信電力")
    ax3.set_ylabel("受信電力 [dBm]", color="#666666")
    ax3.tick_params(axis="y", colors="#666666")
    ax3.set_ylim(-70, -20)

    h2a, l2a = ax2.get_legend_handles_labels()
    h3a, l3a = ax3.get_legend_handles_labels()
    ax2.legend(h2a + h3a, l2a + l3a, loc="lower left", ncol=2, columnspacing=1.0)
    ax2.set_title("(b) 物理層の状態", loc="left", fontweight="bold")

    ax2.set_xlim(0, tmax)
    fig.align_ylabels([ax1, ax2])
    fig.savefig(args.out + ".pdf", bbox_inches="tight")
    fig.savefig(args.out + ".png", dpi=300, bbox_inches="tight")
    print(f"出力: {args.out}.pdf / .png")
    print(f"  手動操作区間として網掛けした範囲: {deg_lo:.1f}–{deg_hi:.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
