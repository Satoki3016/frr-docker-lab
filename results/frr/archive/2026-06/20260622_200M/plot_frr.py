"""
plot_frr.py — System B (FRR OSPF-SR + DiffServ-TE) 比較グラフ生成

results/frr/ 以下の全サブディレクトリ (__pycache__ 除く) を自動検出。

出力:
  compare_throughput.png   … 優先度クラス別スループット比較 (3行)
  compare_rtt.png          … 優先度クラス別 OWD / RTT 比較 (3行)
  compare_packetloss.png   … 優先度クラス別パケットロス率 / WRR達成率 (棒グラフ)
  compare_loss_timeseries.png … 秒ごとパケットロス率時系列 (3行)
  compare_drop_location.png   … ドロップ発生箇所 (2パネル)
"""
import argparse
import re
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np

_parser = argparse.ArgumentParser()
_parser.add_argument("--cr-mbps", type=float, default=99.0,
                     help="CR リンク帯域 (Mbps, WRR目標計算用)")
_parser.add_argument("--tx-mbps", type=float, default=500.0,
                     help="TX 送信レート (Mbps, 損失率計算用)")
_args = _parser.parse_args()

for _f in ["Noto Sans CJK JP", "TakaoPGothic", "IPAPGothic", "VL PGothic"]:
    if any(_f.lower() in p.name.lower() for p in fm.fontManager.ttflist):
        matplotlib.rcParams["font.family"] = _f
        break

matplotlib.rcParams.update({
    "figure.facecolor":  "white",
    "axes.facecolor":    "white",
    "axes.spines.top":   False,
    "axes.spines.right": False,
    "axes.labelsize":    13,
    "axes.titlesize":    13,
    "xtick.labelsize":   11,
    "ytick.labelsize":   11,
    "legend.fontsize":   11,
    "legend.framealpha": 0.85,
    "legend.edgecolor":  "0.8",
    "lines.linewidth":   2.2,
    "grid.alpha":        0.25,
    "grid.linestyle":    ":",
})

BASE        = Path(__file__).resolve().parent
FIGURES_DIR = BASE / "figures"
DPI         = 300
FAILURE_START, FAILURE_END = 20, 40
PLOT_END    = 65

_WRR          = (4, 2, 1)
_CR_LINK_MBPS = _args.cr_mbps
WRR_TARGETS   = [_CR_LINK_MBPS * w / sum(_WRR) for w in _WRR]

# Wong (2011) colorblind-safe palette for traffic classes
PRIORITIES = [
    ("AF41 (高優先)", "#0072B2", 1, "Tx1"),
    ("AF42 (中優先)", "#E69F00", 2, "Tx2"),
    ("AF43 (低優先)", "#009E73", 3, "Tx3"),
]
CLS_LABELS = ["AF41\n(高優先)", "AF42\n(中優先)", "AF43\n(低優先)"]
CLS_COLORS = ["#0072B2", "#E69F00", "#009E73"]

_OWD_NAMES = {1: "owd_af41.log", 2: "owd_af42.log", 3: "owd_af43.log"}

# ── シナリオ自動検出 ──────────────────────────────────────────────────
def _discover_scenarios():
    dirs = sorted(d for d in BASE.iterdir() if d.is_dir() and d.name != "__pycache__")
    result = []
    for d in dirs:
        name = d.name
        if "normal" in name and "failure" not in name:
            color, ls, is_fail = "#2ca02c", "-", False
        elif "reroute" in name:
            color, ls, is_fail = "#1f77b4", "-", True
        elif "failure" in name:
            color, ls, is_fail = "#d62728", "--", True
        else:
            color, ls, is_fail = "tab:gray", "-", False
        result.append((name, name, color, ls, is_fail))
    return result

def has_data(dirpath: Path) -> bool:
    def _has_nonzero_csv(p: Path) -> bool:
        if not p.exists():
            return False
        count = sum(
            1 for line in p.read_text(errors="ignore").splitlines()
            if not line.startswith("time") and line.strip()
            and not all(v.strip() == "0" for v in line.split(",")[1:])
        )
        return count > 5

    if _has_nonzero_csv(dirpath / "htb_class_stats.csv"):
        return True
    if _has_nonzero_csv(dirpath / "throughput.csv"):
        return True
    _chk = re.compile(r"time=[0-9.]+\s*ms")
    for _, _, _, tx in PRIORITIES:
        ping = dirpath / f"{tx}_ping.log"
        if ping.exists() and _chk.search(ping.read_text(errors="ignore")):
            return True
    return False

def active_scenarios():
    return [(d, n, c, ls, f) for d, n, c, ls, f in _discover_scenarios()
            if has_data(BASE / d)]

# ── 保存 ──────────────────────────────────────────────────────────────
def _save(fig, out: Path):
    FIGURES_DIR.mkdir(exist_ok=True)
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    fig.savefig(FIGURES_DIR / out.name, dpi=DPI, bbox_inches="tight")
    print(f"[*] {out.name}")

# ── データ読み込み ────────────────────────────────────────────────────
def _load_throughput(csv_path, col):
    rows = []
    for line in Path(csv_path).read_text().splitlines():
        if line.startswith("time") or not line.strip():
            continue
        parts = line.split(",")
        if len(parts) <= col:
            continue
        try:
            rows.append((float(parts[0]), int(parts[col]) * 8 / 1e6))
        except ValueError:
            continue
    rows.sort(key=lambda x: x[0])
    return ([r[0] for r in rows], [r[1] for r in rows]) if rows else ([], [])

_OWD_RE  = re.compile(r"\[([0-9]+\.[0-9]+)\].*seq=\d+.*owd=([0-9.-]+) ms")
_PING_RE = re.compile(r"^\[([0-9]+\.[0-9]+)\].*time=([0-9.]+)\s*ms")
_SEQ_RE  = re.compile(r'\[([0-9]+\.[0-9]+)\].*icmp_seq=([0-9]+)')

def _load_owd(path: Path):
    ts, vals, t0 = [], [], None
    for line in path.read_text(errors="ignore").splitlines():
        m = _OWD_RE.search(line)
        if m:
            t = float(m.group(1))
            if t0 is None: t0 = t
            ts.append(t - t0); vals.append(float(m.group(2)))
    return ts, vals

def _load_ping_rtt(path: Path):
    ts, vals, t0 = [], [], None
    for line in path.read_text(errors="ignore").splitlines():
        m = _PING_RE.match(line.strip())
        if m:
            t = float(m.group(1))
            if t0 is None: t0 = t
            ts.append(t - t0); vals.append(float(m.group(2)))
    return ts, vals

def _find_owd(dirpath: Path, col: int):
    for name in (_OWD_NAMES.get(col, ""), f"Tx{col}_owd.log"):
        if name and (dirpath / name).exists():
            return dirpath / name
    return None

def _failure_zone(ax):
    ax.axvspan(FAILURE_START, FAILURE_END, alpha=0.08, color="red", zorder=0)
    ax.axvline(FAILURE_START, color="#d62728", ls="--", lw=1.1, alpha=0.7)
    ax.axvline(FAILURE_END,   color="#1f77b4", ls="--", lw=1.1, alpha=0.7)
    ax.grid(True, axis="y")

def _load_per_class_throughput(dirpath: Path, col: int):
    """leri-cr1 + leri-cr2 の HTB stats を合算して返す。
    failure_reroute では te_monitor が cr2 に切り替えるため両方の合算が必要。
    failure では cr2 はゼロのまま → 合算 = cr1 のみ = 障害中はゼロ。
    """
    htb1 = dirpath / "htb_class_stats.csv"
    htb2 = dirpath / "htb_class_stats_cr2.csv"

    t1, mb1 = (_load_throughput(htb1, col) if htb1.exists() else ([], []))
    t2, mb2 = (_load_throughput(htb2, col) if htb2.exists() else ([], []))

    if t1 or t2:
        d1 = dict(zip(t1, mb1))
        d2 = dict(zip(t2, mb2))
        all_t = sorted(set(t1) | set(t2))
        vals  = [d1.get(t, 0.0) + d2.get(t, 0.0) for t in all_t]
        if all_t:
            return all_t, vals

    return _load_throughput(dirpath / "throughput.csv", col)

# ── compare_throughput.png ────────────────────────────────────────────
def compare_throughput(active):
    fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True)
    fig.suptitle("スループット比較 (FRR OSPF-SR + DiffServ-TE WRR 4:2:1)",
                 fontsize=14, fontweight="bold", y=1.01)

    for ax, (pri_label, pri_color, col, _), wrr_target in zip(axes, PRIORITIES, WRR_TARGETS):
        for d, n, c, ls, _ in active:
            t, mb = _load_per_class_throughput(BASE / d, col)
            if t:
                ax.plot(t, mb, label=n, color=c, linestyle=ls)
        ax.axhline(wrr_target, color=pri_color, ls=":", lw=1.5, alpha=0.6,
                   label=f"WRR目標 ({wrr_target:.1f} Mbps)")
        ax.set_xlim(0, PLOT_END); ax.set_ylim(bottom=0)
        ax.set_ylabel("スループット (Mbps)", fontsize=12)
        ax.set_title(pri_label, color=pri_color, fontweight="bold")
        ax.legend(loc="lower right", fontsize=10)
        _failure_zone(ax)

    y = axes[0].get_ylim()[1]
    axes[0].text(FAILURE_START + 0.5, y * 0.97, "障害開始",
                 color="#d62728", fontsize=9, va="top")
    axes[0].text(FAILURE_END   + 0.5, y * 0.97, "障害回復",
                 color="#1f77b4", fontsize=9, va="top")
    axes[-1].set_xlabel("経過時間 (s)", fontsize=12)
    fig.tight_layout()
    _save(fig, BASE / "compare_throughput.png")
    plt.close(fig)

# ── compare_rtt.png ───────────────────────────────────────────────────
def compare_rtt(active):
    fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True)

    has_owd = any(_find_owd(BASE / d, col) is not None
                  for d, *_ in active for _, _, col, _ in PRIORITIES)
    metric  = "OWD" if has_owd else "RTT"
    fig.suptitle(f"片道遅延 ({metric}) 比較  (FRR OSPF-SR + DiffServ-TE)",
                 fontsize=14, fontweight="bold", y=1.01)

    for ax, (pri_label, pri_color, col, tx) in zip(axes, PRIORITIES):
        all_vals = []
        for d, n, c, ls, _ in active:
            owd_p  = _find_owd(BASE / d, col)
            ping_p = BASE / d / f"{tx}_ping.log"
            if owd_p:
                t, vals = _load_owd(owd_p)
            elif ping_p.exists():
                t, vals = _load_ping_rtt(ping_p)
            else:
                continue
            if t:
                ax.plot(t, vals, label=n, color=c, linestyle=ls, alpha=0.85)
                all_vals.extend(vals)
        if all_vals:
            ax.set_ylim(bottom=0, top=float(np.percentile(all_vals, 95)) * 1.3)
        ax.set_xlim(0, PLOT_END)
        ax.set_ylabel(f"{metric} (ms)", fontsize=12)
        ax.set_title(pri_label, color=pri_color, fontweight="bold")
        ax.legend(loc="upper right", fontsize=10)
        _failure_zone(ax)

    y = axes[0].get_ylim()[1]
    axes[0].text(FAILURE_START + 0.5, y * 0.97, "障害開始",
                 color="#d62728", fontsize=9, va="top")
    axes[0].text(FAILURE_END   + 0.5, y * 0.97, "障害回復",
                 color="#1f77b4", fontsize=9, va="top")
    axes[-1].set_xlabel("経過時間 (s)", fontsize=12)
    fig.tight_layout()
    _save(fig, BASE / "compare_rtt.png")
    plt.close(fig)

# ── compare_packetloss.png ────────────────────────────────────────────
def compare_packetloss(active):
    """障害区間(t=FAILURE_START〜FAILURE_END)のパケットロス率を比較。"""
    import csv as _csv

    RX_KEYS = ["rx1_bytes_per_sec", "rx2_bytes_per_sec", "rx3_bytes_per_sec"]
    TX_RATE_BPS = _args.tx_mbps * 1e6

    def _window_loss(dirpath):
        p = dirpath / "throughput.csv"
        if not p.exists():
            return [100.0, 100.0, 100.0]
        rows = [r for r in _csv.DictReader(p.read_text().splitlines())
                if FAILURE_START <= float(r["time"]) <= FAILURE_END]
        if not rows:
            return [100.0, 100.0, 100.0]
        losses = []
        for k in RX_KEYS:
            rx_bps = sum(float(r[k]) for r in rows) / len(rows) * 8
            losses.append(min(100.0, (1 - rx_bps / TX_RATE_BPS) * 100))
        return losses

    loss_data = {n: _window_loss(BASE / d) for d, n, *_ in active}

    n_sc  = len(active)
    x     = np.arange(3)
    width = 0.65 / max(n_sc, 1)

    fig, ax = plt.subplots(figsize=(9, 6))
    fig.suptitle(
        f"障害区間 (t = {FAILURE_START}〜{FAILURE_END} s) パケットロス率\n"
        "迂回なし (failure) ≈ 100%   /   自動迂回 (failure_reroute) ≈ 通常時水準",
        fontsize=13, fontweight="bold"
    )

    for i, (_, n, c, *_) in enumerate(active):
        vals   = loss_data.get(n, [100.0] * 3)
        offset = (i - (n_sc - 1) / 2) * width
        bars   = ax.bar(x + offset, vals, width, label=n,
                        color=c, alpha=0.85, edgecolor="white", linewidth=0.5)
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2,
                    v + 0.8,
                    f"{v:.1f}%", ha="center", va="bottom",
                    fontsize=10, fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(CLS_LABELS, fontsize=12)
    ax.set_ylabel("パケットロス率 (%)", fontsize=13)
    ax.set_ylim(0, 112)
    ax.grid(axis="y")
    ax.legend(fontsize=11, loc="upper left")

    fig.tight_layout()
    _save(fig, BASE / "compare_packetloss.png")
    plt.close(fig)

# ── compare_loss_timeseries.png ───────────────────────────────────────
def compare_loss_timeseries(active):
    """秒ごとのパケットロス率時系列。"""
    import csv as _csv

    TX_RATE_BPS = _args.tx_mbps * 1e6
    RX_KEYS = ["rx1_bytes_per_sec", "rx2_bytes_per_sec", "rx3_bytes_per_sec"]

    def _load_loss_series(dirpath):
        p = dirpath / "throughput.csv"
        if not p.exists():
            return [[], []], [[], []], [[], []]
        rows = list(_csv.DictReader(p.read_text().splitlines()))
        result = []
        for k in RX_KEYS:
            ts, ls = [], []
            for r in rows:
                rx_bps = float(r[k]) * 8
                ts.append(float(r["time"]))
                ls.append(min(100.0, (1 - rx_bps / TX_RATE_BPS) * 100))
            result.append((ts, ls))
        return result

    fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
    fig.suptitle(
        "秒ごとパケットロス率時系列  (FRR OSPF-SR + DiffServ-TE)\n"
        "障害区間 (赤帯): 迂回なし → 100% ロス ／ 自動迂回 → 迅速回復",
        fontsize=13, fontweight="bold", y=1.01
    )

    for ax, (pri_label, pri_color, _, __), ki in zip(axes, PRIORITIES, range(3)):
        ax.set_title(pri_label, color=pri_color, fontweight="bold")
        for d, n, c, ls, _ in active:
            series = _load_loss_series(BASE / d)
            ts, vals = series[ki]
            if ts:
                ax.plot(ts, vals, color=c, ls=ls, label=n, alpha=0.9)
        _failure_zone(ax)
        ax.set_ylabel("ロス率 (%)", fontsize=12)
        ax.set_ylim(0, 108)
        ax.legend(fontsize=10, loc="lower left")

    axes[-1].set_xlabel("経過時間 (s)", fontsize=12)
    axes[-1].set_xlim(0, PLOT_END)
    axes[0].text(FAILURE_START + 0.5, 105, "障害開始",
                 color="#d62728", fontsize=9, va="top")
    axes[0].text(FAILURE_END   + 0.5, 105, "障害回復",
                 color="#1f77b4", fontsize=9, va="top")

    fig.tight_layout()
    _save(fig, BASE / "compare_loss_timeseries.png")
    plt.close(fig)

# ── compare_drop_location.png ─────────────────────────────────────────
def compare_drop_location(active):
    """LER_Ingressのドロップ発生を2パネル(leri-cr1/cr2)で比較。
    CR1/CR2/CR3のegress側はドロップなしと確認済み。"""
    import csv as _csv

    def _load_total_drops(dirpath, node, iface):
        """tc_drops.csv から (node, iface) の全クラス合算ドロップ/秒を返す"""
        p = dirpath / "tc_drops.csv"
        if not p.exists():
            return [], []
        time_drops: dict = {}
        for row in _csv.DictReader(p.read_text().splitlines()):
            if row["node"] == node and row["iface"] == iface:
                t = float(row["time"])
                time_drops[t] = time_drops.get(t, 0.0) + float(row["drops_per_sec"])
        if not time_drops:
            return [], []
        ts = sorted(time_drops)
        return ts, [time_drops[t] for t in ts]

    PANELS = [
        ("LER_Ingress", "leri-cr1", "LER_Ingress → CR1 (leri-cr1)"),
        ("LER_Ingress", "leri-cr2", "LER_Ingress → CR2 (leri-cr2)"),
    ]

    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    fig.suptitle(
        "パケットドロップ発生箇所  (FRR OSPF-SR + DiffServ-TE)\n"
        "ドロップは LER_Ingress HTBキューに集中。CR1/CR2/CR3 egress: 0 drops",
        fontsize=13, fontweight="bold", y=1.02
    )

    any_fail = any(f for *_, f in active)

    for ax, (node, iface, panel_title) in zip(axes, PANELS):
        plotted = False
        for d, n, c, ls, _ in active:
            ts, drops = _load_total_drops(BASE / d, node, iface)
            if ts:
                ax.plot(ts, drops, color=c, ls=ls, label=n, alpha=0.9)
                plotted = True
        if any_fail:
            _failure_zone(ax)
        elif plotted:
            ax.grid(True, axis="y")
        ax.set_title(panel_title, fontweight="bold")
        ax.set_ylabel("ドロップ数/秒", fontsize=12)
        ax.set_xlim(0, PLOT_END)
        ax.set_ylim(bottom=0)
        ax.legend(fontsize=10, loc="upper right")

    axes[1].text(
        0.02, 0.95,
        "注: CR1 / CR2 / CR3 の egress (cr*-lere) はドロップなし (0 drops/s)",
        transform=axes[1].transAxes, fontsize=10, va="top",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="#fffde7", edgecolor="0.7", alpha=0.9)
    )
    axes[0].text(FAILURE_START + 0.5, axes[0].get_ylim()[1] * 0.97,
                 "障害開始", color="#d62728", fontsize=9, va="top")
    axes[0].text(FAILURE_END   + 0.5, axes[0].get_ylim()[1] * 0.97,
                 "障害回復", color="#1f77b4", fontsize=9, va="top")

    axes[-1].set_xlabel("経過時間 (s)", fontsize=12)
    fig.tight_layout()
    _save(fig, BASE / "compare_drop_location.png")
    plt.close(fig)

# ── エントリポイント ──────────────────────────────────────────────────
if __name__ == "__main__":
    active = active_scenarios()
    if not active:
        print("[ERROR] データなし (frr/ 以下のサブフォルダを確認)")
        raise SystemExit(1)

    print(f"検出シナリオ: {[n for _, n, *_ in active]}")
    print(f"WRR目標: AF41={WRR_TARGETS[0]:.1f}M / AF42={WRR_TARGETS[1]:.1f}M / "
          f"AF43={WRR_TARGETS[2]:.1f}M")
    print()

    compare_throughput(active)
    compare_rtt(active)
    compare_packetloss(active)
    compare_loss_timeseries(active)
    compare_drop_location(active)

    print("\n完了")
