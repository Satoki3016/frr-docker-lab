#!/usr/bin/env python3
"""radwin_experiment.sh run の結果を1枚にまとめる。

timebase.txt を使って controller.csv (絶対時刻) と
throughput.csv / path_stats.csv (相対秒) を同一時間軸に載せる。
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

C41,C42,C43 = "#0072B2","#E69F00","#CC79A7"
CCR1,CCR2,CCR3 = "#D55E00","#009E73","#56B4E9"
CEST,CAPP = "#E69F00","#0072B2"



def _plot_power(a, D, ct, s1, s2, lo, hi, tmax):
    """受信電力のみの単段図。アンテナ操作が信号強度に与えた影響を示す。"""
    import statistics as _st
    fig, ax = plt.subplots(1, 1, figsize=(7.4, 3.4))
    ax.axvspan(lo, hi, color="#F0F0F0", zorder=0)

    ax.plot(ct, s1, lw=1.2, color="#009E73", zorder=3, label="無線1 (ch1, 58.32 GHz)")
    ax.plot(ct, s2, lw=1.2, color="#CC79A7", zorder=3, label="無線2 (ch4, 64.80 GHz)")

    # 注記は入れない。回復後の水準が初期より良いため、
    # 「基準」という単一の水平線を引くとかえって誤解を招く。

    ax.set_ylabel("受信電力 [dBm]")
    ax.set_xlabel("計測開始からの経過時間 [s]")
    ax.set_ylim(-68, -8)
    ax.set_xlim(0, tmax)
    ax.grid(axis="y", lw=0.4, color="0.9", zorder=0)
    ax.legend(loc="upper center", ncol=2, columnspacing=1.4)
    ax.set_title("無線区間の受信電力", loc="left", fontweight="bold")
    ax.text((lo + hi) / 2, -65.5, "アンテナの向きを変えた区間", ha="center",
            fontsize=8, color="#777777", style="italic")

    out = a.out or str(D / "result_signal_power")
    fig.savefig(out + ".pdf", bbox_inches="tight")
    fig.savefig(out + ".png", dpi=300, bbox_inches="tight")
    print(f"出力: {out}.pdf / .png   (網掛け {lo:.0f}-{hi:.0f}s)")
    return 0


def _plot_report(a, D, th, ps, ct, est, app, act, lo, hi, tmax):
    """報告用の2段構成。上が無線区間、下が受信ノード。物理層は載せない。"""
    fig, (a1, a2, a3) = plt.subplots(3, 1, figsize=(7.4, 7.4), sharex=True,
                                     gridspec_kw={"height_ratios": [1.0, 1.0, 0.85],
                                                  "hspace": 0.13})
    for ax in (a1, a2, a3):
        ax.axvspan(lo, hi, color="#F0F0F0", zorder=0)

    # 上段: 無線区間 (CR1) の実測と制御
    tp = [x[0] for x in ps]
    a1.plot(tp, [x[1] for x in ps], lw=1.2, color=CCR1, zorder=4,
            label="実測スループット")
    a1.step(ct, app, where="post", lw=1.3, color=CAPP, ls="--", zorder=3,
            label="制御が適用した整形レート")
    a1.step(ct, est, where="post", lw=1.2, color=CEST, alpha=0.9, zorder=2,
            label=r"推定容量 $\hat{C}$")
    a1.set_ylabel("無線区間のレート [Gbps]")
    a1.set_ylim(0, 3.4)
    a1.grid(axis="y", lw=0.4, color="0.9", zorder=0)
    a1.legend(loc="upper center", ncol=3, columnspacing=1.4)
    a1.set_title("(a) 無線区間のスループット", loc="left", fontweight="bold")
    a1.text((lo+hi)/2, 0.22, "アンテナの向きを変えた区間", ha="center",
            fontsize=8, color="#777777", style="italic")

    # 下段: 受信ノードのクラス別スループット
    t = [x[0] for x in th]
    for i, (nm, c) in enumerate(zip(["AF41 (高優先)", "AF42 (中)", "AF43 (低)"],
                                    [C41, C42, C43])):
        a2.plot(t, [x[i+1] for x in th], lw=1.2, color=c, label=nm, zorder=3)
    a2.set_ylabel("受信スループット [Gbps]")
    a2.set_ylim(0, 11.8)
    a2.set_yticks([0, 2, 4, 6, 8, 10])
    a2.grid(axis="y", lw=0.4, color="0.9", zorder=0)
    a2.legend(loc="upper center", ncol=3, columnspacing=1.4)
    a2.set_title("(b) 受信ノードのスループット", loc="left", fontweight="bold")

    # (c) 基準比。絶対値では AF42/AF43 の減少が目盛りに埋もれて見えないため、
    #     劣化前 (網掛けの直前) を 100 % として正規化する。
    base_win = [x for x in th if 5 <= x[0] <= lo - 1]
    base = [sum(x[i+1] for x in base_win) / len(base_win) for i in range(3)]
    for i, (nm, c) in enumerate(zip(["AF41 (高優先)", "AF42 (中)", "AF43 (低)"],
                                    [C41, C42, C43])):
        a3.plot(t, [x[i+1] / base[i] * 100 for x in th], lw=1.2, color=c,
                label=nm, zorder=3)
    a3.axhline(100, lw=0.7, ls=":", color="#888888", zorder=2)
    a3.set_ylabel("劣化前を 100 とした比 [%]")
    a3.set_ylim(60, 124)
    a3.set_yticks([70, 80, 90, 100, 110])
    a3.grid(axis="y", lw=0.4, color="0.9", zorder=0)
    a3.legend(loc="upper center", ncol=3, columnspacing=1.4)
    a3.set_title("(c) 劣化前を基準とした変化", loc="left", fontweight="bold")
    a3.set_xlabel("計測開始からの経過時間 [s]")
    a3.set_xlim(0, tmax)

    fig.align_ylabels([a1, a2, a3])
    out = a.out or str(D / "result_throughput")
    fig.savefig(out + ".pdf", bbox_inches="tight")
    fig.savefig(out + ".png", dpi=300, bbox_inches="tight")
    print(f"出力: {out}.pdf / .png   (網掛け {lo:.0f}-{hi:.0f}s / 有効 0-{tmax:.0f}s)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True,
                    help="実験タグ (例 20260918_success_dynamic_integrated) "
                         "または results/frr からの相対パス")
    ap.add_argument("--out", default=None)
    ap.add_argument("--tmax", type=float, default=None, help="送信終了秒 (既定: 自動)")
    ap.add_argument("--layout", choices=["full", "report", "power"], default="full",
                    help="full=3段(物理層含む) / report=2段(無線区間と受信ノード) / power=受信電力のみ")
    ap.add_argument("--scenario", default=None,
                    help="計測フォルダ frr_<シナリオ> (既定: フォルダ内に1つだけあればそれを使う)")
    a = ap.parse_args()
    D = result_dir(a.dir)
    if a.scenario:
        S = D / f"frr_{a.scenario}"
    else:
        # run は normal / failure_reroute / manual のどれか1つを保存する
        cands = sorted(d for d in D.glob("frr_*") if (d / "throughput.csv").exists())
        if len(cands) != 1:
            sys.exit(f"計測フォルダを1つに決められません: {[c.name for c in cands]} "
                     "(--scenario で指定してください)")
        S = cands[0]

    tb = dict(l.strip().split("=",1) for l in (S/"timebase.txt").read_text().splitlines() if "=" in l)
    t0 = int(tb["throughput_t0_epoch_ms"]) / 1000.0

    th = [(int(r[0]), *[float(r[i])*8/1e9 for i in (1,2,3)])
          for r in list(csv.reader((S/"throughput.csv").open()))[1:] if r[0].isdigit()]
    ps = [(int(r[0]), *[float(r[i])*8/1e9 for i in (1,2,3)])
          for r in list(csv.reader((S/"path_stats.csv").open()))[1:] if r[0].isdigit()]
    cl = list(csv.DictReader((D/"controller.csv").open()))

    # 送信が終わった後の末尾は主張に含めない
    tmax = a.tmax
    if tmax is None:
        base = sum(x[1] for x in th if 5 <= x[0] <= 20) / len([x for x in th if 5 <= x[0] <= 20])
        tail = [t for t,v,_,_ in th if t > 30 and v < base*0.5]
        tmax = (min(tail) - 1) if tail else max(x[0] for x in th)

    th = [x for x in th if x[0] <= tmax]; ps = [x for x in ps if x[0] <= tmax]
    ct  = [float(r["time"]) - t0 for r in cl]
    est = [float(r["est_mbps"])/1000 for r in cl]
    app = [int(r["applied_mbps"])/1000 for r in cl]
    m1  = [int(r["hop1_mcs"]) for r in cl]; m2 = [int(r["hop2_mcs"]) for r in cl]
    s1  = [float(r["hop1_dbm"]) if r["hop1_dbm"] else None for r in cl]
    s2  = [float(r["hop2_dbm"]) if r["hop2_dbm"] else None for r in cl]
    act = [r["action"] for r in cl]

    # 網掛けは受信電力で決める。アンテナの向きを直接反映するため。
    # ただし正常時も数dB振れるので、移動中央値で平滑化してから判定する。
    import statistics as _st
    mn = [min(s1[i], s2[i]) if s1[i] is not None and s2[i] is not None else None
          for i in range(len(ct))]
    W = 5
    sm = []
    for i in range(len(mn)):
        w = [x for x in mn[max(0,i-W//2):i+W//2+1] if x is not None]
        sm.append(_st.median(w) if w else None)
    good = _st.median([x for x in sm[:8] if x is not None])
    thr = good - 8.0
    deg = [ct[i] for i in range(len(ct)) if sm[i] is not None and sm[i] < thr]
    lo, hi = (min(deg), max(deg)) if deg else (0.0, 0.0)

    if a.layout == "report":
        return _plot_report(a, D, th, ps, ct, est, app, act, lo, hi, tmax)
    if a.layout == "power":
        return _plot_power(a, D, ct, s1, s2, lo, hi, tmax)

    fig, (a1,a2,a3) = plt.subplots(3,1, figsize=(7.4,7.2), sharex=True,
                                   gridspec_kw={"height_ratios":[1.3,1.1,1.0],"hspace":0.12})
    for ax in (a1,a2,a3): ax.axvspan(lo,hi,color="#F0F0F0",zorder=0)

    t = [x[0] for x in th]
    for i,(nm,c) in enumerate(zip(["AF41 (高優先)","AF42 (中)","AF43 (低)"],[C41,C42,C43])):
        a1.plot(t,[x[i+1] for x in th], lw=1.1, color=c, label=nm, zorder=3)
    a1.set_ylabel("受信スループット [Gbps]"); a1.set_ylim(0,11.8)
    a1.set_yticks([0,2,4,6,8,10])
    a1.grid(axis="y",lw=0.4,color="0.9",zorder=0)
    a1.legend(loc="upper center",ncol=3,columnspacing=1.4)
    a1.set_title("(a) クラス別スループット — AF41 は無線容量の低下に影響されない",
                 loc="left",fontweight="bold")
    a1.text((lo+hi)/2, 1.0, "アンテナの向きを変えた区間", ha="center",
            fontsize=8, color="#777777", style="italic")

    tp = [x[0] for x in ps]
    for i,(nm,c) in enumerate(zip(["CR1 (無線)","CR2 (有線)","CR3 (有線)"],[CCR1,CCR2,CCR3])):
        a2.plot(tp,[x[i+1] for x in ps], lw=1.1, color=c, label=nm, zorder=3)
    a2.step(ct, app, where="post", lw=1.3, color=CAPP, ls="--", zorder=4,
            label="制御が適用した CR1 整形レート")
    a2.step(ct, est, where="post", lw=1.2, color=CEST, zorder=3, alpha=0.9,
            label=r"推定容量 $\hat{C}$")
    a2.set_ylabel("経路別レート [Gbps]"); a2.set_ylim(0,13.2)
    a2.set_yticks([0,2,4,6,8,10])
    a2.grid(axis="y",lw=0.4,color="0.9",zorder=0)
    a2.legend(loc="upper center",ncol=2,columnspacing=1.4)
    a2.set_title("(b) 経路別の配分と動的制御", loc="left", fontweight="bold")

    a3.step(ct,m1,where="post",lw=1.3,color="#009E73",label="無線1 MCS")
    a3.step(ct,m2,where="post",lw=1.3,color="#CC79A7",label="無線2 MCS")
    a3.set_ylabel("MCS インデックス"); a3.set_ylim(0,13.5); a3.set_yticks([0,3,6,9,12])
    a3.grid(axis="y",lw=0.4,color="0.9",zorder=0)
    a3.set_xlabel("計測開始からの経過時間 [s]")
    a4 = a3.twinx(); a4.spines["top"].set_visible(False)
    a4.spines["right"].set_visible(True); a4.spines["right"].set_color("#888888")
    a4.plot(ct,s1,lw=0.8,color="#999999",label="無線1 受信電力")
    a4.plot(ct,s2,lw=0.8,color="#999999",ls=":",label="無線2 受信電力")
    a4.set_ylabel("受信電力 [dBm]",color="#666666"); a4.tick_params(axis="y",colors="#666666")
    a4.set_ylim(-70,-10)
    h3,l3=a3.get_legend_handles_labels(); h4,l4=a4.get_legend_handles_labels()
    a3.legend(h3+h4,l3+l4,loc="lower left",ncol=2,columnspacing=1.2)
    a3.set_title("(c) 物理層の状態", loc="left", fontweight="bold")
    a3.set_xlim(0,tmax)

    fig.align_ylabels([a1,a2,a3])
    out = a.out or str(D/"integrated_run")
    fig.savefig(out+".pdf", bbox_inches="tight")
    fig.savefig(out+".png", dpi=300, bbox_inches="tight")
    print(f"出力: {out}.pdf / .png   (網掛け {lo:.0f}-{hi:.0f}s / 有効 0-{tmax:.0f}s)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
