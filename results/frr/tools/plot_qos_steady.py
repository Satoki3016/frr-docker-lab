#!/usr/bin/env python3
"""
plot_qos_steady.py — 定常状態 (frr_normal) における QoS 効果の2枚看板図

輻輳下 DiffServ-TE (HTB SP+WRR) が実現する2つの効果を1枚で示す:
  (a) クラス別スループット — Strict Priority 有効 / 無効の対比。
      SP有効ではAF41が優先保護されリンク容量まで到達する一方、SP無効では
      3クラスがHTBのquantum比 4:2:1 で機械的に分配されるだけになる。
  (b) クラス別片道遅延 (OWD) — SP有効時。AF41は輻輳下でもキュー待ちが
      ほぼ生じない（<1ms）のに対し、AF42/AF43は優先度に応じてキュー待ちが
      桁違いに増大する。y軸は対数スケール。

データソース:
  20260721_c2_sp_enabled/frr_normal/{throughput.csv, owd_af4{1,2,3}.log}
  20260721_c2_sp_uniform/frr_normal/throughput.csv

集計区間は t=5〜18 s（起動直後の過渡を除いた定常区間）。

使い方:
    python3 plot_qos_steady.py [--lang en|ja] [--outdir DIR]
"""
import argparse
import csv
import re
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

BASE = Path(__file__).resolve().parent.parent

SP_ENABLED = "qos/c2/20260721_c2_sp_enabled"
SP_UNIFORM = "qos/c2/20260721_c2_sp_uniform"

# 定常区間 [s]（起動過渡を除く）
T_LO, T_HI = 5, 18

CLASSES = ["af41", "af42", "af43"]
CLASS_LABELS = ["High", "Medium", "Low"]

# 条件で色分け（一貫方式）: SP enabled = 青, SP disabled = 赤
COLOR_ENABLED = "#418BBF"
COLOR_DISABLED = "#DC4748"

_TS_RE = re.compile(r'\[([0-9]+\.[0-9]+)\]\s+seq=\d+\s+owd=([0-9.-]+)\s*ms')

_TXT = {
    "en": {
        "ax_a": "(a) Per-class throughput",
        "ax_b": "(b) Per-class one-way delay",
        "ylabel_a": "Throughput (Gbps)",
        "ylabel_b": "One-way delay (ms)",
        "xlabel_common": "Traffic class",
        "leg_enabled": "SP + WRR",
        "leg_disabled": "WRR",
    },
    "ja": {
        "ax_a": "(a) クラス別スループット",
        "ax_b": "(b) クラス別片道遅延 (OWD)",
        "ylabel_a": "スループット (Gbps)",
        "ylabel_b": "片道遅延 (ms)",
        "xlabel_common": "トラフィッククラス",
        "leg_enabled": "SP + WRR",
        "leg_disabled": "WRR only",
    },
}


def load_throughput_mean(path: Path, t_lo: int, t_hi: int) -> np.ndarray:
    """throughput.csv から t_lo<=t<=t_hi の平均 (rx1,rx2,rx3) [bytes/s] を返す。"""
    rows = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            t = int(row["time"])
            if t in rows:
                continue  # 計測スクリプトの再送行を除去（先着優先）
            rows[t] = (
                float(row["rx1_bytes_per_sec"]),
                float(row["rx2_bytes_per_sec"]),
                float(row["rx3_bytes_per_sec"]),
            )
    sel = [rows[t] for t in sorted(rows) if t_lo <= t <= t_hi]
    return np.array(sel).mean(axis=0)


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


def owd_stats(ts, owd, t_lo, t_hi):
    """定常区間内の (median, p95, min, max) [ms] を返す。"""
    sel = (ts >= t_lo) & (ts <= t_hi)
    o = owd[sel]
    return np.median(o), np.percentile(o, 95), o.min(), o.max()


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
        "font.size": 14, "axes.labelsize": 14, "axes.titlesize": 14,
        "xtick.labelsize": 13, "ytick.labelsize": 13,
        "legend.fontsize": 13, "legend.framealpha": 0.9,
    })

    # ── データ読み込み ──────────────────────────────────────────────
    tput_en = load_throughput_mean(
        BASE / SP_ENABLED / "frr_normal" / "throughput.csv", T_LO, T_HI) * 8 / 1e9
    tput_dis = load_throughput_mean(
        BASE / SP_UNIFORM / "frr_normal" / "throughput.csv", T_LO, T_HI) * 8 / 1e9

    def collect_owd(tag):
        med, p95, mn = [], [], []
        for cls in CLASSES:
            ts, owd = load_owd(BASE / tag / "frr_normal" / f"owd_{cls}.log")
            m, p, lo, _ = owd_stats(ts, owd, T_LO, T_HI)
            med.append(m)
            p95.append(p)
            mn.append(lo)
        return np.array(med), np.array(p95), np.array(mn)

    owd_med_en, owd_p95_en, owd_min_en = collect_owd(SP_ENABLED)
    owd_med_dis, owd_p95_dis, owd_min_dis = collect_owd(SP_UNIFORM)

    # ── 描画 ────────────────────────────────────────────────────────
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(10.4, 4.4), layout="constrained")

    # (a) スループット: SP有効 vs 無効
    x = np.arange(len(CLASSES))
    width = 0.36
    bars_en = ax_a.bar(x - width / 2, tput_en, width, color=COLOR_ENABLED,
                        edgecolor="white", linewidth=0.6, label=T["leg_enabled"])
    bars_dis = ax_a.bar(x + width / 2, tput_dis, width, color=COLOR_DISABLED,
                         edgecolor="white", linewidth=0.6, label=T["leg_disabled"])

    for bars in (bars_en, bars_dis):
        for b in bars:
            h = b.get_height()
            ax_a.text(b.get_x() + b.get_width() / 2, h + 0.18, f"{h:.2f} Gbps",
                       ha="center", va="bottom", fontsize=11.5, fontweight="bold")

    ax_a.set_xticks(x)
    ax_a.set_xticklabels(CLASS_LABELS)
    ax_a.set_xlabel(T["xlabel_common"])
    ax_a.set_ylabel(T["ylabel_a"])
    ax_a.set_ylim(0, 9.6)
    ax_a.set_title(T["ax_a"], loc="left", fontweight="bold", pad=8)
    ax_a.legend(loc="upper right")

    # (b) OWD: SP有効 vs 無効、クラス別（線形軸）
    y_hi = float(max(owd_p95_en.max(), owd_p95_dis.max())) * 1.22
    # 棒が低いクラスは2条件のラベルが同じ高さで隣接し重なるため、
    # WRR only 側だけラベルを一段持ち上げる
    for offset, med, p95, mn, color, lab, lift in (
        (-width / 2, owd_med_en, owd_p95_en, owd_min_en, COLOR_ENABLED, T["leg_enabled"], 0.0),
        (+width / 2, owd_med_dis, owd_p95_dis, owd_min_dis, COLOR_DISABLED, T["leg_disabled"], 0.055),
    ):
        ax_b.bar(x + offset, med, width, color=color,
                 edgecolor="white", linewidth=0.6, label=lab)
        ax_b.errorbar(x + offset, med,
                      yerr=[np.clip(med - mn, 0, None), np.clip(p95 - med, 0, None)],
                      fmt="none", ecolor="0.2", elinewidth=1.2, capsize=3, zorder=5)
        for xi, m, hi in zip(x + offset, med, p95):
            label = f"{m:.2f} ms" if m < 10 else f"{m:.0f} ms"
            off = y_hi * (0.02 + (lift if hi < y_hi * 0.15 else 0.0))
            ax_b.text(xi, hi + off, label, ha="center", va="bottom",
                      fontsize=11.5, fontweight="bold", color="#1c1c1c")

    ax_b.set_ylim(0, y_hi)
    ax_b.set_xticks(x)
    ax_b.set_xticklabels(CLASS_LABELS)
    ax_b.set_xlabel(T["xlabel_common"])
    ax_b.set_ylabel(T["ylabel_b"])
    ax_b.set_title(T["ax_b"], loc="left", fontweight="bold", pad=8)
    ax_b.legend(loc="upper left")


    outdir = Path(args.outdir) if args.outdir else BASE / SP_ENABLED / args.lang
    outdir.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf"):
        p = outdir / f"qos_steady.{ext}"
        fig.savefig(p, dpi=300)
        print(f"[*] {p}")

    # 数値サマリを標準出力へ（原稿・スライドへの転記用）
    print(f"\n--- throughput (Gbps), mean over t={T_LO}-{T_HI}s ---")
    print(f"  SP enabled : AF41={tput_en[0]:.3f}  AF42={tput_en[1]:.3f}  AF43={tput_en[2]:.3f}")
    print(f"  SP disabled: AF41={tput_dis[0]:.3f}  AF42={tput_dis[1]:.3f}  AF43={tput_dis[2]:.3f}")
    ratio = tput_dis / tput_dis[2]
    print(f"  SP disabled ratio (normalized to AF43): {ratio[0]:.2f} : {ratio[1]:.2f} : {ratio[2]:.2f}")

    print(f"\n--- one-way delay (ms), median [min, p95], t={T_LO}-{T_HI}s ---")
    for lab, m_en, p_en, l_en, m_di, p_di, l_di in zip(
            CLASS_LABELS, owd_med_en, owd_p95_en, owd_min_en,
            owd_med_dis, owd_p95_dis, owd_min_dis):
        print(f"  {lab}: SP enabled={m_en:9.3f} [{l_en:.3f}, {p_en:.3f}]   "
              f"SP disabled={m_di:9.3f} [{l_di:.3f}, {p_di:.3f}]")


if __name__ == "__main__":
    main()
