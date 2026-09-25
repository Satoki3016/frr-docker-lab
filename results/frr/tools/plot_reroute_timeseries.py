#!/usr/bin/env python3
"""
plot_reroute_timeseries.py — 自動迂回の効果を受信スループットの時系列で示す図

Results(2/2) 用。normal / failure(迂回なし) / failure(自動迂回) の3シナリオを
重ねる。--cls all（既定）ではクラスごとに1段ずつ、計3段で描く。

読み方:
  自動迂回の谷は障害窓の【中】で閉じる  → 網が自力で迂回した
  迂回なしの谷は障害窓の【端】まで続く  → netem 解除で戻っただけ

注意: throughput.csv は 1 秒サンプリングであり、断時間そのものは分解できない。
断の精密値 (2.92 s) は 20 ms 間隔の OWD プローブによる別図・本文で述べること。
本図の役割は「復旧したか否か」を直感的に示すことに限定する。

見た目の調整:
  モジュール先頭の FONT / COLOR / LINE / LAYOUT の4辞書のみを編集すればよい。
  図中の文字サイズ・色・線の太さ・余白はすべてこの4辞書を参照しており、
  描画部に数値を直接書いていない。

使い方:
    python3 plot_reroute_timeseries.py [--tag TAG] [--cls af41|af42|af43|all]
                                       [--lo 0] [--hi 60] [--lang en|ja]
"""
import argparse
import csv
import math
from pathlib import Path
from result_paths import result_dir

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator
import numpy as np

BASE = Path(__file__).resolve().parent.parent

DEFAULT_TAG = "qos/c2/20260721_c2_sp_enabled"

# 障害注入区間 [s]
FAIL_LO, FAIL_HI = 20.0, 40.0

# ── フォントサイズ（ここだけ編集すれば全要素に反映される）──────────────
FONT = {
    "base":        18,   # 明示指定のない要素の既定値
    "panel_title": 14,   # 各段の見出し（High-priority traffic など）
    "xlabel":      18,   # 横軸ラベル
    "ylabel":      20,   # 縦軸ラベル（横軸と別値。揃えたいなら同じ数値にする）
    "tick":        18,   # 目盛りラベル
    "legend":      22,   # 凡例
}

# ── 色 ────────────────────────────────────────────────────────────
# 系列の色がそのまま凡例の色になる。
COLOR = {
    "normal":     "#4C9F4C",   # 障害なし
    "no_reroute": "#DC4748",   # 障害あり・迂回なし
    "reroute":    "#418BBF",   # 障害あり・自動迂回
    "fail_span":  "#ff0000",   # 障害注入区間の網掛け
    "fail_line":  "0.45",      # 障害区間の境界を示す縦点線
}

# ── 線の太さ・スタイル ──────────────────────────────────────────────
# ダッシュ長は明示指定。既定の "--" / "-." は凡例のハンドル内で1周期に満たず、
# 実線と区別できなくなるため使わない。
LINE = {
    "normal_w":     2.0,                  # 障害なしの線幅
    "no_reroute_w": 2.0,                  # 迂回なしの線幅
    "reroute_w":    2.2,                  # 自動迂回の線幅（最も注目させる系列）
    "normal_ls":    "solid",
    "no_reroute_ls": (0, (6, 2)),         # 破線
    "reroute_ls":    (0, (9, 2, 2, 2)),   # 一点鎖線
    "fail_line_w":  1.1,                  # 障害区間の境界線
    "grid_w":       0.8,                  # グリッド線
}

# ── レイアウト ────────────────────────────────────────────────────
# bbox_inches="tight" を使わないため、余白は下記で固定する。
# フォントを大きくして要素がはみ出す場合はここを調整する。
LAYOUT = {
    "width":        11.0,   # 図の幅 [inch]
    "panel_height":  1.95,  # 1段あたりの高さ [inch]
    "extra_height":  1.2,   # 凡例・横軸ラベル用の追加高さ [inch]
    "left":          0.115, # 左余白（縦軸ラベルと目盛りの領域）
    "right":         0.985,
    "top":           0.885, # 上余白（凡例の領域）
    "bottom":        0.095, # 下余白（横軸ラベルの領域）
    "hspace":        0.42,  # 段の間隔
    "span_alpha":    0.07,  # 障害区間の網掛けの濃さ
    "grid_alpha":    0.25,
    "legend_y":      1.0,   # 凡例の垂直位置（図の上端を1とする）
    "legend_ncol":   3,
    "legend_handle": 2.6,   # 凡例の線見本の長さ（線種を判別できる長さが要る）
    "legend_colsp":  1.6,   # 凡例の列間隔
    "ytick_headroom": 1.15, # 縦軸上限＝データ最大値のこの倍数を丸めた値
}

CLS_COL = {"af41": "rx1_bytes_per_sec",
           "af42": "rx2_bytes_per_sec",
           "af43": "rx3_bytes_per_sec"}
CLS_TITLE = {"af41": "High-priority traffic",
             "af42": "Medium-priority traffic",
             "af43": "Low-priority traffic"}

# (ディレクトリ名, ラベルキー, 色キー, 線種キー, 線幅キー)
SCENARIOS = [
    ("frr_normal",          "leg_normal", "normal",     "normal_ls",     "normal_w"),
    ("frr_failure",         "leg_nore",   "no_reroute", "no_reroute_ls", "no_reroute_w"),
    ("frr_failure_reroute", "leg_re",     "reroute",    "reroute_ls",    "reroute_w"),
]

_TXT = {
    "en": {
        "ylabel": "Throughput (Gbps)",
        "xlabel": "time (s)",
        "leg_normal": "normal",
        "leg_nore": "failure",
        "leg_re": "failure + reroute",
    },
    "ja": {
        "ylabel": "受信スループット (Gbps)",
        "xlabel": "経過時間 (s)",
        "leg_normal": "障害なし",
        "leg_nore": "迂回なし",
        "leg_re": "自動迂回",
    },
}


def nice_top(v: float) -> float:
    """v 以上で最も近い「きりのいい」上限を返す。目盛りを 0/中央/上限 の3本に揃えるため。"""
    if v <= 0:
        return 1.0
    exp = math.floor(math.log10(v))
    base = 10.0 ** exp
    for k in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if k * base >= v - 1e-12:
            return k * base
    return 10.0 * base


def load_series(path: Path, col: str):
    """throughput.csv から (時刻[s], スループット[Gbps]) を返す。重複行は先着優先。"""
    rows = {}
    with path.open(newline="") as f:
        for r in csv.DictReader(f):
            t = int(r["time"])
            if t not in rows:
                rows[t] = float(r[col]) * 8 / 1e9
    ts = np.array(sorted(rows))
    return ts, np.array([rows[t] for t in ts])


def setup_font(lang: str):
    """言語に応じたフォントと、共通の描画スタイルを設定する。"""
    if lang == "en":
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
        "axes.grid": True,
        "grid.alpha": LAYOUT["grid_alpha"],
        "grid.linestyle": ":",
        "grid.linewidth": LINE["grid_w"],
        "font.size": FONT["base"],
        "axes.labelsize": FONT["xlabel"],
        "xtick.labelsize": FONT["tick"],
        "ytick.labelsize": FONT["tick"],
        "legend.fontsize": FONT["legend"],
    })


def draw_panel(ax, root: Path, cls: str, T: dict, lo: float, hi: float):
    """1クラス分（1段）を描く。"""
    ax.axvspan(FAIL_LO, FAIL_HI, color=COLOR["fail_span"],
               alpha=LAYOUT["span_alpha"], zorder=0)
    for xv in (FAIL_LO, FAIL_HI):
        ax.axvline(xv, color=COLOR["fail_line"], linestyle=":",
                   linewidth=LINE["fail_line_w"], zorder=1)

    ymax = 0.0
    for scen, key, ckey, lskey, lwkey in SCENARIOS:
        ts, v = load_series(root / scen / "throughput.csv", CLS_COL[cls])
        sel = (ts >= lo) & (ts <= hi)
        ax.plot(ts[sel], v[sel], color=COLOR[ckey], linestyle=LINE[lskey],
                linewidth=LINE[lwkey], label=T[key], zorder=3,
                solid_capstyle="round")
        ymax = max(ymax, v[sel].max())

    ax.set_xlim(lo, hi)
    # 上限をきりのいい値に丸め、目盛りを 0/中央/上限 の3本に固定する。
    # 自動選択に任せると段ごとに目盛り数が変わり、段の比較がしにくくなる。
    top = nice_top(ymax * LAYOUT["ytick_headroom"])
    ax.set_ylim(0, top)
    ax.yaxis.set_major_locator(FixedLocator([0, top / 2, top]))
    ax.set_title(CLS_TITLE[cls], loc="left",
                 fontsize=FONT["panel_title"], fontweight="bold", pad=4)


def build_figure(root: Path, classes: list, T: dict, lo: float, hi: float):
    fig, axes = plt.subplots(
        len(classes), 1, sharex=True, squeeze=False,
        figsize=(LAYOUT["width"],
                 LAYOUT["panel_height"] * len(classes) + LAYOUT["extra_height"]))
    axes = axes[:, 0]
    # 上部は凡例、左は縦軸ラベル、下は横軸ラベルの領域として固定的に確保する
    fig.subplots_adjust(left=LAYOUT["left"], right=LAYOUT["right"],
                        top=LAYOUT["top"], bottom=LAYOUT["bottom"],
                        hspace=LAYOUT["hspace"])

    for ax, cls in zip(axes, classes):
        draw_panel(ax, root, cls, T, lo, hi)

    axes[-1].set_xlabel(T["xlabel"])
    axes[len(classes) // 2].set_ylabel(T["ylabel"], fontsize=FONT["ylabel"])

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center",
               bbox_to_anchor=(0.5, LAYOUT["legend_y"]),
               ncol=LAYOUT["legend_ncol"], fontsize=FONT["legend"], frameon=False,
               handlelength=LAYOUT["legend_handle"],
               columnspacing=LAYOUT["legend_colsp"])
    return fig


def print_summary(root: Path, classes: list, T: dict):
    for cls in classes:
        print(f"\n--- {CLS_TITLE[cls]} throughput (Gbps), t=20-25 s ---")
        for scen, key, *_ in SCENARIOS:
            ts, v = load_series(root / scen / "throughput.csv", CLS_COL[cls])
            w = (ts >= 20) & (ts <= 25)
            print(f"  {T[key]:24s}: "
                  + "  ".join(f"t={int(t)}:{x:.2f}" for t, x in zip(ts[w], v[w])))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default=DEFAULT_TAG)
    ap.add_argument("--cls", default="all", choices=tuple(CLS_COL) + ("all",))
    ap.add_argument("--lo", type=float, default=0.0)
    ap.add_argument("--hi", type=float, default=60.0)
    ap.add_argument("--lang", default="en", choices=("en", "ja"))
    ap.add_argument("--outdir", default=None)
    args = ap.parse_args()

    T = _TXT[args.lang]
    setup_font(args.lang)

    root = result_dir(args.tag)
    classes = list(CLS_COL) if args.cls == "all" else [args.cls]

    fig = build_figure(root, classes, T, args.lo, args.hi)

    outdir = Path(args.outdir) if args.outdir else root / args.lang
    outdir.mkdir(parents=True, exist_ok=True)
    stem = f"reroute_timeseries_{args.cls}"
    for ext in ("png", "pdf"):
        p = outdir / f"{stem}.{ext}"
        fig.savefig(p, dpi=300)
        print(f"[*] {p}")

    print_summary(root, classes, T)


if __name__ == "__main__":
    main()
