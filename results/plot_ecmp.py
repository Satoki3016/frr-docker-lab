"""
plot_ecmp.py — System A (ip netns / ECMP / RSVP-TE)
出力: compare_throughput.png  compare_rtt.png  compare_packetloss.png
"""
import re
from pathlib import Path
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np

for _f in ["Noto Sans CJK JP", "TakaoPGothic", "IPAPGothic", "VL PGothic"]:
    if any(_f.lower() in p.name.lower() for p in fm.fontManager.ttflist):
        matplotlib.rcParams["font.family"] = _f
        break

matplotlib.rcParams.update({
    "figure.facecolor":  "white",
    "axes.facecolor":    "white",
    "axes.spines.top":   False,
    "axes.spines.right": False,
    "axes.titlesize":    13,
    "axes.labelsize":    13,
    "legend.fontsize":   11,
    "legend.framealpha": 0.85,
    "legend.edgecolor":  "0.8",
    "xtick.labelsize":   11,
    "ytick.labelsize":   11,
    "lines.linewidth":   2.2,
    "grid.alpha":        0.25,
    "grid.linestyle":    ":",
})

BASE = Path(__file__).resolve().parent
DPI  = 300
FAILURE_START, FAILURE_END = 20, 40

_WRR = (4, 2, 1)
_CR_TOTAL_MBPS = 300.0
WRR_TARGETS = [_CR_TOTAL_MBPS * w / sum(_WRR) for w in _WRR]

SCENARIOS = [
    ("normal",          "normal",       "#2ca02c", "-",  False),
    ("failure",         "failure",      "#d62728", "--", True),
    ("failure_rsvp_v2", "failure_rsvp", "#1f77b4", "-",  True),
    ("failure_rsvp",    "failure_rsvp", "#1f77b4", "-",  True),
]
PRIORITIES = [
    ("AF41 (高優先)", "#0072B2", 1, "Tx1"),
    ("AF42 (中優先)", "#E69F00", 2, "Tx2"),
    ("AF43 (低優先)", "#009E73", 3, "Tx3"),
]
CLS_LABELS  = ["AF41\n(高優先)", "AF42\n(中優先)", "AF43\n(低優先)"]
CLS_COLORS  = ["#0072B2", "#E69F00", "#009E73"]
CLS_KEYS    = ["AF41(高)", "AF42(中)", "AF43(低)"]

# ── データ読み込み ────────────────────────────────────────────────────
def load_throughput(csv_path, col):
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

_PING_RE = re.compile(r"\[([0-9]+\.[0-9]+)\].*icmp_seq=([0-9]+).*time=([0-9.]+)")

def load_rtt(log_path):
    ts, rtt = [], []
    for line in Path(log_path).read_text(errors="ignore").splitlines():
        m = _PING_RE.search(line)
        if m:
            ts.append(float(m.group(1)))
            rtt.append(float(m.group(3)))
    if not ts:
        return [], []
    t0 = ts[0]
    return [x - t0 for x in ts], rtt

def active_scenarios():
    seen, result = set(), []
    for d, n, c, ls, f in SCENARIOS:
        if n in seen:
            continue
        if (BASE / d / "throughput.csv").exists():
            seen.add(n)
            result.append((d, n, c, ls, f))
    return result

# ── 装飾ヘルパー ──────────────────────────────────────────────────────
def _zone(ax):
    ax.axvspan(FAILURE_START, FAILURE_END, alpha=0.08, color="red", zorder=0)
    ax.axvline(FAILURE_START, color="#d62728", ls="--", lw=1.1, alpha=0.7)
    ax.axvline(FAILURE_END,   color="#1f77b4", ls="--", lw=1.1, alpha=0.7)
    ax.grid(True, axis="y")

def _save(fig, out: Path):
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    print(f"[*] {out.name}")

# ── グラフ ─────────────────────────────────────────────────────────────
def plot_throughput(active):
    fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True)
    fig.suptitle("スループット比較  (ECMP / RSVP-TE  WRR 4:2:1)",
                 fontsize=14, fontweight="bold", y=1.01)

    for ax, (pri, color, col, _), wrr_target in zip(axes, PRIORITIES, WRR_TARGETS):
        for d, n, c, ls, _ in active:
            t, mb = load_throughput(BASE / d / "throughput.csv", col)
            if t:
                ax.plot(t, mb, label=n, color=c, linestyle=ls)
        ax.axhline(wrr_target, color=color, ls=":", lw=1.5, alpha=0.6,
                   label=f"WRR目標 ({wrr_target:.1f} Mbps)")
        ax.set_xlim(0, 59); ax.set_ylim(bottom=0)
        ax.set_ylabel("スループット (Mbps)", fontsize=12)
        ax.set_title(pri, color=color, fontweight="bold")
        ax.legend(loc="lower right", fontsize=10)
        _zone(ax)

    y = axes[0].get_ylim()[1]
    axes[0].text(FAILURE_START + 0.5, y * 0.97, "障害開始",
                 color="#d62728", fontsize=9, va="top")
    axes[0].text(FAILURE_END   + 0.5, y * 0.97, "障害回復",
                 color="#1f77b4", fontsize=9, va="top")
    axes[-1].set_xlabel("経過時間 (s)", fontsize=12)
    fig.tight_layout()
    _save(fig, BASE / "compare_throughput.png")
    plt.close(fig)

def plot_rtt(active):
    fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True)
    fig.suptitle("往復遅延 RTT 比較  (ECMP / RSVP-TE)",
                 fontsize=14, fontweight="bold", y=1.01)

    for ax, (pri, color, _, tx) in zip(axes, PRIORITIES):
        all_rtt = []
        for d, n, c, ls, _ in active:
            p = BASE / d / f"{tx}_ping.log"
            if not p.exists():
                continue
            t, rtt = load_rtt(p)
            if t:
                ax.plot(t, rtt, label=n, color=c, linestyle=ls, alpha=0.85)
                all_rtt.extend(rtt)
        if all_rtt:
            ax.set_ylim(bottom=0, top=float(np.percentile(all_rtt, 99)) * 1.3)
        ax.set_ylabel("RTT (ms)", fontsize=12)
        ax.set_title(pri, color=color, fontweight="bold")
        ax.legend(loc="upper right", fontsize=10)
        _zone(ax)

    axes[0].set_xlim(0, 60)
    y = axes[0].get_ylim()[1]
    axes[0].text(FAILURE_START + 0.5, y * 0.97, "障害開始",
                 color="#d62728", fontsize=9, va="top")
    axes[0].text(FAILURE_END   + 0.5, y * 0.97, "障害回復",
                 color="#1f77b4", fontsize=9, va="top")
    axes[-1].set_xlabel("経過時間 (s)", fontsize=12)
    fig.tight_layout()
    _save(fig, BASE / "compare_rtt.png")
    plt.close(fig)

def plot_packetloss(active):
    classes = ["AF41(高)", "AF42(中)", "AF43(低)"]

    panel_data = []
    for d, n, c, ls, _ in active:
        csv = BASE / d / "packet_loss.csv"
        if not csv.exists():
            continue
        rows = []
        for line in csv.read_text().splitlines():
            if line.startswith("node") or not line.strip():
                continue
            parts = line.split(",")
            if len(parts) < 6:
                continue
            try:
                rows.append({"node": parts[0], "dir": parts[2], "cls": parts[3],
                             "sent": int(parts[4]), "dropped": int(parts[5])})
            except ValueError:
                continue

        def _agg(direction, node_key, rows=rows):
            out = {}
            for cls in classes:
                m = [r for r in rows if r["cls"] == cls
                     and r["dir"] == direction and node_key in r["node"]]
                s = sum(r["sent"] for r in m)
                dr = sum(r["dropped"] for r in m)
                out[cls] = dr / (s + dr) * 100 if (s + dr) > 0 else 0.0
            return out

        ler = _agg("egress", "LER_Ingress_ns")
        cr  = _agg("egress", "CoreRouter")

        _, mbps_list = zip(*[
            (load_throughput(BASE / d / "throughput.csv", col)[0],
             load_throughput(BASE / d / "throughput.csv", col)[1])
            for col in [1, 2, 3]
        ]) if (BASE / d / "throughput.csv").exists() else ([], [[], [], []])
        e2e = {}
        for cls, tgt, mb in zip(classes, WRR_TARGETS, mbps_list):
            mb2 = mb[1:-1] if len(mb) > 4 else mb
            avg = float(np.mean(mb2)) if mb2 else 0.0
            e2e[cls] = min(100.0, avg / tgt * 100) if tgt > 0 else 0.0

        panel_data.append((n, c, ler, cr, e2e))

    if not panel_data:
        print("[skip] compare_packetloss: packet_loss.csv なし")
        return

    x       = np.arange(len(classes))
    n_bars  = len(panel_data)
    width   = 0.65 / max(n_bars, 1)
    offsets = [(i - (n_bars - 1) / 2) * width for i in range(n_bars)]
    tgt_str = "/".join(f"{t:.0f}M" for t in WRR_TARGETS)

    fig, axes = plt.subplots(1, 3, figsize=(14, 5))
    fig.suptitle("パケットロス率 / WRR達成率  (ECMP / RSVP-TE)",
                 fontsize=14, fontweight="bold")

    for ax, (key, title, is_achieve) in zip(axes, [
        ("ler", "LER_Ingress HTB/WRR\n(輻輳ドロップ率)",      False),
        ("cr",  "CoreRouter HTB\n(中継ドロップ率)",            False),
        ("e2e", f"WRR 達成率\n(目標: {tgt_str} = 100%)",      True),
    ]):
        max_val = 0
        for i, (n, c, ler, cr, e2e) in enumerate(panel_data):
            data = {"ler": ler, "cr": cr, "e2e": e2e}[key]
            vals = [data.get(cls, 0.0) for cls in classes]
            bars = ax.bar(x + offsets[i], vals, width, label=n,
                          color=c, alpha=0.85, edgecolor="white", linewidth=0.5)
            for bar, v in zip(bars, vals):
                ax.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + 0.3,
                        f"{v:.1f}%", ha="center", va="bottom",
                        fontsize=10, fontweight="bold")
            max_val = max(max_val, max(vals))
        ax.set_xticks(x); ax.set_xticklabels(CLS_LABELS, fontsize=12)
        ax.set_title(title, fontsize=12)
        ax.grid(axis="y")
        if is_achieve:
            ax.set_ylabel("達成率 (%)", fontsize=13)
            ax.set_ylim(0, 100)
            ax.axhline(100, color="black", lw=0.8, ls="--", alpha=0.5)
            ax.legend(fontsize=11, loc="lower left")
        else:
            ax.set_ylabel("パケットロス率 (%)", fontsize=13)
            ax.set_ylim(0, max(max_val * 1.35, 5))
            ax.legend(fontsize=11, loc="upper left")

    fig.tight_layout()
    _save(fig, BASE / "compare_packetloss.png")
    plt.close(fig)

if __name__ == "__main__":
    active = active_scenarios()
    if not active:
        print("[ERROR] データなし (results/normal/, failure/, failure_rsvp/ を確認してください)")
        raise SystemExit(1)
    print(f"シナリオ: {[n for _, n, *_ in active]}")
    plot_throughput(active)
    plot_rtt(active)
    plot_packetloss(active)
    print("完了")
