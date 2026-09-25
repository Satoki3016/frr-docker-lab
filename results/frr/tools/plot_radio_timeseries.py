#!/usr/bin/env python3
"""無線区間の時間変化 (スループット・MCS・受信電力) を1枚にまとめる。

入力 (結果フォルダ):
  controller.csv  必須。MCS と受信電力 (約2秒周期, 絶対時刻)
  live.csv        任意。radwin_live_monitor.py --log-csv の出力 (スループット, 絶対時刻)
                  無ければスループットの段を描かない。

MCS と受信電力はどちらもホップの親機 (.31 / .33) の `iw station dump` による。
  MCS      = 親機の送信 MCS (親機 → 子機の向き)
  受信電力 = 親機が子機から受けたフレームの信号強度 [dBm]

使い方: python3 results/frr/tools/plot_radio_timeseries.py --dir 20260925_success_control_wcmp_01
"""
from __future__ import annotations
import argparse, csv, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from result_paths import result_dir  # noqa: E402
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.font_manager as fm

for _f in ["Noto Sans CJK JP", "TakaoPGothic", "IPAPGothic"]:
    if any(_f.lower() in p.name.lower() for p in fm.fontManager.ttflist):
        matplotlib.rcParams["font.family"] = _f; break
matplotlib.rcParams.update({
    "figure.facecolor":"white","axes.facecolor":"white",
    "axes.spines.top":False,"axes.spines.right":False,"axes.linewidth":0.8,
    "axes.labelsize":9,"axes.titlesize":9,"axes.titlepad":4,"axes.labelpad":3,
    "xtick.labelsize":8,"ytick.labelsize":8,"legend.fontsize":8,
    "xtick.major.width":0.8,"ytick.major.width":0.8,
    "legend.framealpha":0.95,"legend.edgecolor":"0.8"})

CH1, CH2 = "#009E73", "#CC79A7"          # 無線1 (.31→.32), 無線2 (.33→.34)
CTX, CRX, CAPP = "#D55E00", "#0072B2", "0.35"
HOP1 = "無線1 (ch1, 58.32 GHz)"
HOP2 = "無線2 (ch4, 64.80 GHz)"


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="結果フォルダ (タグ名または results/frr からの相対パス)")
    ap.add_argument("--out", default=None, help="出力パス (拡張子なし)")
    a = ap.parse_args()
    D = result_dir(a.dir)
    C = list(csv.DictReader((D / "controller.csv").open()))
    t0 = num(C[0]["time"])
    ct = [num(r["time"]) - t0 for r in C]
    L = list(csv.DictReader((D / "live.csv").open())) if (D / "live.csv").exists() else []
    events = [(ct[i], r["action"]) for i, r in enumerate(C) if r["action"] in ("down", "up", "link_down")]

    n = 3 if L else 2
    fig, axes = plt.subplots(n, 1, figsize=(7.4, 2.35 * n + 0.4), sharex=True,
                             gridspec_kw={"hspace": 0.2})
    tag = iter("abc")

    if L:
        ax = axes[0]
        lt = [num(r["time"]) - t0 for r in L]
        ax.plot(lt, [num(r["wireless_tx_gbps"]) for r in L], lw=1.0, color=CTX, label="無線 送信 (cr1-lere)")
        ax.plot(lt, [num(r["wireless_rx_gbps"]) for r in L], lw=1.0, color=CRX, label="無線 受信 (lere-cr1)")
        ax.step(ct, [num(r["applied_mbps"]) / 1000 for r in C], where="post", lw=1.1, ls="--",
                color=CAPP, label="CR1 整形レート (制御)")
        # live_monitor の負荷は fwmark を持たず HTB を素通りする (無線の素の実力)。
        # そのときは整形レートではなく推定容量と比べるのが正しいので両方を描く。
        ax.step(ct, [num(r["est_mbps"]) / 1000 for r in C], where="post", lw=1.1, ls=":",
                color="#E69F00", label="推定容量 (制御)")
        ax.set_ylabel("スループット [Gbps]")
        ymax = max([num(r["wireless_tx_gbps"]) for r in L] + [num(r["applied_mbps"]) / 1000 for r in C])
        ax.set_ylim(0, ymax * 1.6)                    # 凡例と制御イベント名の置き場
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, 0.83), ncol=2, columnspacing=1.2)
        ax.set_title(f"({next(tag)}) 無線区間のスループット", loc="left", fontweight="bold")

    ax = axes[-2]
    ax.step(ct, [num(r["hop1_mcs"]) for r in C], where="post", lw=1.3, color=CH1, label=HOP1)
    ax.step(ct, [num(r["hop2_mcs"]) for r in C], where="post", lw=1.3, color=CH2, label=HOP2)
    ax.set_ylabel("送信 MCS")
    ax.set_ylim(0, 13)
    ax.set_yticks(range(0, 13, 2))
    ax.legend(loc="lower left", ncol=2, columnspacing=1.4)
    ax.set_title(f"({next(tag)}) 親機の送信 MCS (MCS 12 が最大, PHY 4620 Mbps)", loc="left", fontweight="bold")

    ax = axes[-1]
    ax.plot(ct, [num(r["hop1_dbm"]) for r in C], "-o", lw=1.0, ms=2.0, color=CH1, label=HOP1)
    ax.plot(ct, [num(r["hop2_dbm"]) for r in C], "-o", lw=1.0, ms=2.0, color=CH2, label=HOP2)
    ax.set_ylabel("受信電力 [dBm]")
    ax.set_ylim(-70, -10)
    ax.legend(loc="lower left", ncol=2, columnspacing=1.4)
    ax.set_title(f"({next(tag)}) 親機の受信電力 (子機から受けたフレーム)", loc="left", fontweight="bold")
    ax.set_xlabel("制御開始からの経過時間 [s]")
    ax.set_xlim(0, ct[-1] + 2)

    for ax in axes:
        ax.grid(axis="y", lw=0.4, color="0.9", zorder=0)
        for t, _ in events:
            ax.axvline(t, lw=0.6, ls=":", color="0.55", zorder=0)
    top = axes[0]
    span = ct[-1] + 2
    last, row = -1e9, 0
    for t, act in events:
        row = row + 1 if t - last < 0.06 * span else 0   # 近接するラベルは一段下げる
        last = t
        top.annotate(act, (t, 1.0), xycoords=("data", "axes fraction"), xytext=(2, -2 - 9 * row),
                     textcoords="offset points", ha="left", va="top", fontsize=6.5, color="0.4")

    out = a.out or str(D / "result_radio_timeseries")
    fig.savefig(out + ".pdf", bbox_inches="tight")
    fig.savefig(out + ".png", dpi=300, bbox_inches="tight")
    print(f"出力: {out}.pdf / .png   (スループット: {'あり' if L else 'live.csv なし'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
