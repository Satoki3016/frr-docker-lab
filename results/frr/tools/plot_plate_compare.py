#!/usr/bin/env python3
"""金属板の障害実験の評価用の図 (30 秒と 80 秒の比較、迂回の様子、迂回中の優先制御)。

    python3 results/frr/tools/plot_plate_compare.py

論文の用語だけを使い、1 枚に 1 つの量・凡例は図の中 (plot_plate_experiment.py の --paper と同じ体裁)。
出力: results/frr/radwin/observation/20261013_success_rainobs_01/01_report/figures/eval/
  cmp_loss_duration   各条件の AF41 損失率 (障害なし / 遮蔽 30 秒 / 遮蔽 80 秒、中央値の棒と範囲のひげ)
  path_rate_<条件>    遮蔽 80 秒の代表試行の、経路ごとの送信レート (無線・有線 2 経路)
  wired_drop_<条件>   同じ試行の、有線 2 経路で捨てたパケットのクラス別のレート
                      (入口ルータの各経路の出口と、中継ルータ 2・3 の出口の合計。中継ルータ 1 が入口へ
                      送り返した通信は入口の整形を通らず、中継ルータ 2・3 の出口で捨てられるため)
代表は、各条件の遮蔽 80 秒の 3 試行のうち AF41 損失率が中央値の試行。
"""
from __future__ import annotations

import csv
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plot_plate_experiment as pp  # noqa: E402  (体裁・読み込みを共有する)
from plot_plate_experiment import plt  # noqa: E402

OBS = Path(__file__).resolve().parents[1] / "radwin" / "observation"
RUN30 = OBS / "20261012_success_rainobs_04"
RUN80 = OBS / "20261013_success_rainobs_01"
OUT = RUN80 / "01_report" / "figures" / "eval"
PKT_GBIT = 7000 * 8 / 1e9                     # UDP 長 7,000 B (ヘッダは含めない)
CONDS = [("P", "動的制御\nあり"), ("P3", "分配判定\nを追加"), ("P4", "復帰時の\n待機を追加"),
         ("S", "動的制御\nなし"), ("N", "動的制御・\n経路監視なし")]
NAME = {"P": "動的制御あり", "S": "動的制御なし", "N": "動的制御・経路監視なし"}


def load(obs: Path, label: str, seconds: int) -> list[dict]:
    pp.LABEL, pp.PLATE_OFF = label, pp.PLATE_ON + seconds
    return pp.load_runs(obs)


def fig_duration(r30: list[dict], r80: list[dict]) -> None:
    fig, ax = plt.subplots(figsize=(3.4, 2.45))
    groups = [("障害なし", [r for r in r80 if r["state"] == "none"], "white"),
              ("障害あり（遮蔽30秒）", [r for r in r30 if r["state"] == "fault"], "#A6A6A6"),
              ("障害あり（遮蔽80秒）", [r for r in r80 if r["state"] == "fault"], "#404040")]
    w = 0.26
    top = 0.0
    for j, (lab, g, face) in enumerate(groups):
        for i, (c, _) in enumerate(CONDS):
            v = [r["loss"] for r in g if r["cond"] == c]
            med = st.median(v)
            x = i + (j - 1) * w
            ax.bar(x, med, w, color=face, edgecolor="#333333", lw=0.7, zorder=3, label=lab if i == 0 else None)
            ax.errorbar(x, med, yerr=[[med - min(v)], [max(v) - med]], fmt="none", ecolor="#333333",
                        elinewidth=0.7, capsize=1.8, zorder=4)
            top = max(top, max(v))
    ax.set_xticks(range(len(CONDS)))
    ax.set_xticklabels([lab for _, lab in CONDS], fontsize=6.4)
    ax.set_ylabel("AF41損失率 [%]", fontsize=8)
    ax.set_ylim(0, top * 1.1)
    ax.tick_params(axis="y", labelsize=7.5)
    ax.grid(axis="y", lw=0.4, color="0.88", zorder=0)
    ax.legend(loc="upper left", fontsize=6.8)
    pp._save(fig, OUT / "cmp_loss_duration")


def fig_path_rate(r: dict, cond: str) -> None:
    fig, ax = pp._paper_axes("送信レート [Gbps]")
    rows = list(csv.DictReader((r["dir"] / "path_stats.csv").open()))
    t = [int(x["time"]) for x in rows]
    for i, (lab, col, ls) in enumerate((("無線経路", "#D55E00", "-"), ("有線経路（中継ルータ2）", "#0072B2", "--"),
                                        ("有線経路（中継ルータ3）", "#009E73", ":")), start=1):
        y = [int(x[f"cr{i}_tx_bytes_per_sec"]) * 8 / 1e9 for x in rows]
        tt, yy = pp._trim(t, y)
        ax.plot(tt, yy, color=col, ls=ls, lw=1.2, label=lab)
    ax.set_ylim(0, 12.5)
    ax.set_ylim(0, 14.5)
    ax.legend(loc="upper center", ncol=2, fontsize=6.0, handlelength=2.0, columnspacing=0.6, borderaxespad=0.2)
    pp._save(fig, OUT / f"path_rate_{cond}")


def fig_wired_drop(r: dict, cond: str) -> None:
    fig, ax = pp._paper_axes("有線経路での破棄 [Gbps]")
    acc: dict[tuple[int, str], float] = defaultdict(float)
    for x in csv.DictReader((r["dir"] / "tc_drops.csv").open()):
        if (x["node"], x["iface"]) in (("LER_Ingress", "leri-cr2"), ("LER_Ingress", "leri-cr3"),
                                       ("CR2", "cr2-lere"), ("CR3", "cr3-lere")):
            acc[(int(x["time"]), x["class"])] += float(x["drops_per_sec"]) * PKT_GBIT
    ts = sorted({k[0] for k in acc})
    for c, col, lw, z in (("AF41", "#0072B2", 1.8, 5), ("AF42", "#E69F00", 1.2, 3), ("AF43", "#CC79A7", 1.2, 3)):
        tt, yy = pp._trim(ts, [acc[(s, c)] for s in ts])
        ax.plot(tt, yy, color=col, lw=lw, label=c, zorder=z)
    ax.set_ylim(-0.25, 6.5)                     # 0 のままの AF41 の線が横軸に隠れないように
    ax.legend(loc="upper center", ncol=3, fontsize=6.3, handlelength=1.6, columnspacing=0.8, borderaxespad=0.2)
    pp._save(fig, OUT / f"wired_drop_{cond}")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    r30 = load(RUN30, "plate30", 30)
    r80 = load(RUN80, "plate80", 80)               # 以降の時系列の網掛けは 80 秒 (20〜100 秒)
    fig_duration(r30, r80)
    for c in NAME:
        rep = pp.representative(r80, c)
        fig_path_rate(rep, c)
        fig_wired_drop(rep, c)
        print(f"{NAME[c]}: 代表 {rep['folder'][-3:]} (AF41 損失率 {rep['loss']:.3f}%)")
    print("出力:", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
