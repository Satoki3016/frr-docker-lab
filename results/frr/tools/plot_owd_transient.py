#!/usr/bin/env python3
"""
plot_owd_transient.py — OWD プローブ (20 ms 間隔) による障害遷移の高分解能解析

compare_loss_timeseries.png は iperf3 の 1 秒ビンであり遷移を分解できない。
OWD プローブは 20 ms 間隔で送出されるため、受信が途絶えた区間の開始・終了を
±20 ms で特定できる。本スクリプトはその区間を「通信断」として抽出し、
  (a) OWD 時系列上での断区間（迂回なし vs 自動迂回）
  (b) 全条件での断継続時間の比較
を描画する。

使い方:
    python3 plot_owd_transient.py [--lang en|ja] [--outdir DIR]
"""
import argparse
import re
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

BASE = Path(__file__).resolve().parent.parent

# 断とみなす受信途絶のしきい値 [s]（プローブ間隔 20 ms の 7 倍以上＝明確な途絶）
GAP_THRESHOLD = 0.15

# 主図に使う条件（SP 有効の実機 C2 環境）
PRIMARY = "qos/c2/20260721_c2_sp_enabled"

# 断継続時間の比較に使う全条件
CONDITIONS = [
    ("qos/c2/20260721_c2_sp_enabled",     "Physical testbed\nSP enabled"),
    ("qos/c2/20260721_c2_sp_uniform",     "Physical testbed\nSP disabled"),
    ("qos/veth/20260721_veth9G_sp_enabled", "Virtual testbed\nSP enabled"),
    ("qos/veth/20260721_veth9G_sp_uniform", "Virtual testbed\nSP disabled"),
]

SCENARIOS = [
    ("frr_failure",         "Failure (no reroute)",   "#DC4748", "s"),
    ("frr_failure_reroute", "Failure (auto-reroute)", "#418BBF", "o"),
]

_TXT = {
    "en": {
        "suptitle": "Failure transient resolved by 20 ms OWD probes (high-priority traffic)",
        "ax_a":     "(a) One-way delay of high-priority probes, physical testbed (SP enabled)",
        "ax_b":     "(b) Outage duration across all four conditions",
        "xlabel_a": "Elapsed time (s)",
        "ylabel_a": "One-way delay (ms)",
        "ylabel_b": "Outage duration (s)",
        "inject":   "netem loss 100%\n(t = 20 s)",
        "repair":   "netem cleared\n(t = 40 s)",
        "dead":     "OSPF dead-interval = 3 s",
        "note":     "Outage = interval with no probe received (probe interval 20 ms)",
    },
    "ja": {
        "suptitle": "20 ms OWDプローブによる障害遷移の分解 (高優先トラフィック)",
        "ax_a":     "(a) 高優先プローブの片道遅延, 実機環境 (SP有効)",
        "ax_b":     "(b) 全4条件の通信断継続時間",
        "xlabel_a": "経過時間 (s)",
        "ylabel_a": "片道遅延 (ms)",
        "ylabel_b": "通信断の継続時間 (s)",
        "inject":   "netem損失100%\n(t = 20 s)",
        "repair":   "netem解除\n(t = 40 s)",
        "dead":     "OSPF dead-interval = 3 s",
        "note":     "断 = プローブが1つも届かない区間 (プローブ間隔 20 ms)",
    },
}

_TS_RE = re.compile(r'\[([0-9]+\.[0-9]+)\]\s+seq=\d+\s+owd=([0-9.-]+)\s*ms')


def load_owd(path: Path):
    """OWD ログを (相対時刻[s], OWD[ms]) の配列で返す。"""
    if not path.exists():
        return np.array([]), np.array([])
    ts, owd = [], []
    for line in path.read_text(errors="ignore").splitlines():
        m = _TS_RE.match(line)
        if m:
            ts.append(float(m.group(1)))
            owd.append(float(m.group(2)))
    if not ts:
        return np.array([]), np.array([])
    ts = np.array(ts)
    return ts - ts[0], np.array(owd)


def find_outage(ts, threshold=GAP_THRESHOLD):
    """最長の受信途絶区間を (開始, 終了, 継続) で返す。無ければ None。"""
    if len(ts) < 2:
        return None
    d = np.diff(ts)
    idx = np.where(d > threshold)[0]
    if len(idx) == 0:
        return None
    k = idx[np.argmax(d[idx])]          # 最長の途絶を採用
    return ts[k], ts[k + 1], d[k]


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
        "font.size": 9, "axes.labelsize": 9, "axes.titlesize": 9,
        "legend.fontsize": 8, "legend.framealpha": 0.9,
    })

    fig, (ax_a, ax_b) = plt.subplots(
        2, 1, figsize=(7, 6.2), layout="constrained",
        gridspec_kw={"height_ratios": [1.25, 1.0]})
    fig.suptitle(T["suptitle"], fontsize=10.5, fontweight="bold")

    # ── (a) OWD 時系列 + 断区間 ────────────────────────────────────────
    XLO, XHI = 15.0, 46.0
    for scen, label, color, marker in SCENARIOS:
        ts, owd = load_owd(BASE / PRIMARY / scen / "owd_af41.log")
        if len(ts) == 0:
            continue
        sel = (ts >= XLO) & (ts <= XHI)
        ax_a.plot(ts[sel], owd[sel], linestyle="none", marker=marker,
                  markersize=2.0, color=color, alpha=0.65, label=label)

        out = find_outage(ts)
        if out is None:
            continue
        t0, t1, dur = out
        ax_a.axvspan(t0, t1, color=color, alpha=0.10, zorder=0)
        # 断区間を両端矢印で明示
        y = 1.55 if scen == "frr_failure" else 1.15
        ax_a.annotate("", xy=(t0, y), xytext=(t1, y),
                      arrowprops=dict(arrowstyle="<->", color=color, lw=1.3))
        ax_a.text((t0 + t1) / 2, y + 0.07, f"{dur:.2f} s",
                  ha="center", va="bottom", fontsize=8.5,
                  color=color, fontweight="bold")

    ax_a.set_xlim(XLO, XHI)
    ax_a.set_ylim(0, 2.0)

    ax_a.axvline(20, color="0.35", ls=":", lw=1.0)
    ax_a.axvline(40, color="0.35", ls=":", lw=1.0)
    _bbox = dict(boxstyle="round,pad=0.25", fc="white", ec="0.8", lw=0.5, alpha=0.92)
    ax_a.text(20.25, 0.70, T["inject"], fontsize=7.2, color="0.35",
              ha="left", va="center", linespacing=1.25, bbox=_bbox, zorder=6)
    ax_a.text(39.75, 0.70, T["repair"], fontsize=7.2, color="0.35",
              ha="right", va="center", linespacing=1.25, bbox=_bbox, zorder=6)
    ax_a.set_xlabel(T["xlabel_a"])
    ax_a.set_ylabel(T["ylabel_a"])
    ax_a.set_title(T["ax_a"], loc="left", pad=14, fontweight="bold")
    leg = ax_a.legend(loc="upper right", markerscale=3.5)
    leg.set_zorder(5)

    # ── (b) 全条件の断継続時間 ────────────────────────────────────────
    n = len(CONDITIONS)
    x = np.arange(n)
    width = 0.36
    for j, (scen, label, color, _) in enumerate(SCENARIOS):
        vals = []
        for tag, _lab in CONDITIONS:
            out = find_outage(load_owd(BASE / tag / scen / "owd_af41.log")[0])
            vals.append(out[2] if out else np.nan)
        pos = x + (j - 0.5) * width
        bars = ax_b.bar(pos, vals, width, color=color, label=label,
                        edgecolor="white", linewidth=0.6)
        for xi, v in zip(pos, vals):
            if not np.isnan(v):
                ax_b.text(xi, v + 0.35, f"{v:.2f}", ha="center", va="bottom",
                          fontsize=8, fontweight="bold", color=color)

    # OSPF dead-interval の水準線（断時間が検出時間に支配されることを示す）。
    # 軸内の空きが乏しいため注記は凡例に統合し、はみ出しを構造的に避ける。
    ax_b.axhline(3.0, color="#333333", ls="--", lw=1.1, zorder=3, label=T["dead"])

    ax_b.set_xticks(x)
    ax_b.set_xticklabels([lab for _t, lab in CONDITIONS], fontsize=8)
    ax_b.set_ylabel(T["ylabel_b"])
    ax_b.set_ylim(0, 28)
    ax_b.set_title(T["ax_b"], loc="left", pad=4, fontweight="bold")
    ax_b.legend(loc="upper center", ncol=3, framealpha=0.95, fontsize=7.5,
                columnspacing=1.2, handlelength=2.0)

    fig.text(0.01, -0.005, T["note"], fontsize=7.2, color="0.4")

    outdir = Path(args.outdir) if args.outdir else BASE / PRIMARY / args.lang
    outdir.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf"):
        p = outdir / f"owd_transient.{ext}"
        fig.savefig(p, dpi=300, bbox_inches="tight")
        print(f"[*] {p}")

    # 数値サマリを標準出力へ（原稿・スライドへの転記用）
    print("\n--- outage duration (s), AF41, 20 ms OWD probes ---")
    for tag, lab in CONDITIONS:
        row = []
        for scen, label, _c, _m in SCENARIOS:
            out = find_outage(load_owd(BASE / tag / scen / "owd_af41.log")[0])
            row.append(f"{label}={out[2]:.3f}" if out else f"{label}=n/a")
        print(f"  {tag:30s} " + "  ".join(row))


if __name__ == "__main__":
    main()
