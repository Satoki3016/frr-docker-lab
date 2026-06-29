"""
plot_rx.py — 全シナリオ・優先度別グラフ生成 (学会発表用)

使い方:
    python3 results/plot_rx.py                          # 全シナリオ自動生成
    python3 results/plot_rx.py results/failure_rsvp_v2 # 1シナリオのみ
    python3 results/plot_rx.py --show-loss              # ロス率オーバーレイ表示

出力先:
    results/figures/  ← 全グラフの集約フォルダ (学会発表用)
    results/<scenario>/Docker_*.png  ← 実験データディレクトリ内 (後方互換)
"""

import json
import re
import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np

# ── 日本語フォント ────────────────────────────────────────────────────
_ja_fonts = ["Noto Sans CJK JP", "Noto Sans CJK SC", "Noto Sans CJK TC",
             "TakaoPGothic", "IPAPGothic", "VL PGothic"]
for _f in _ja_fonts:
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

# ── シナリオ設定 ──────────────────────────────────────────────────────
# (dirname, 凡例名, 線色, 線種, is_failure)
# failure_rsvp_v2 を優先して使用し、なければ failure_rsvp にフォールバック
SCENARIOS = [
    ("normal",          "normal",        "#2ca02c", "-",  False),
    ("failure",         "failure",       "#d62728", "--", True),
    ("failure_rsvp_v2", "failure_rsvp",  "#1f77b4", "-",  True),
    ("failure_rsvp",    "failure_rsvp",  "#1f77b4", "-",  True),
]

# FRR OSPF-SR + DiffServ-TE (System B) — results/frr/ 以下に格納
FRR_SCENARIOS = [
    ("frr_normal",          "frr_normal",          "#2ca02c", "-",  False),
    ("frr_failure",         "frr_failure",         "#d62728", "--", True),
    ("frr_failure_reroute", "frr_failure_reroute", "#1f77b4", "-",  True),
]

# ── 優先度クラス設定 ──────────────────────────────────────────────────
# (凡例名, 色, throughput列idx, Tx名, Rx名)
PRIORITIES = [
    ("AF41 (高優先)", "#0072B2", 1, "Tx1", "Rx1"),
    ("AF42 (中優先)", "#E69F00", 2, "Tx2", "Rx2"),
    ("AF43 (低優先)", "#009E73", 3, "Tx3", "Rx3"),
]

# ── 軸設定 ────────────────────────────────────────────────────────────
THR_X_MIN = 0
THR_X_MAX = 59
THR_Y_MIN = 0
THR_Y_MAX = None

DLY_X_MIN = 0
DLY_X_MAX = 60
DLY_Y_MIN = 0
DLY_Y_MAX = None
DLY_Y_ZOOM = "auto"   # "auto" → 95パーセンタイル×1.2  / 数値 → 固定上限

FAILURE_START = 20
FAILURE_END   = 40
POLICE_DOWN   = 21   # RSVP-TE 2-link police 適用タイミング (障害検知 ~1s後)
POLICE_UP     = 41   # RSVP-TE 3-link police 復旧タイミング

FIG_DPI   = 300
SHOW_LOSS = False

BASE        = Path(__file__).resolve().parent
FIGURES_DIR = BASE / "figures"   # 全グラフ集約フォルダ

def _save(fig, primary_path: Path, fig_name: str = None):
    """primary_path に保存し、FIGURES_DIR にも保存する。
    fig_name を指定すると figures/ 内での名前を上書きできる (シナリオ prefix 付き用)。"""
    FIGURES_DIR.mkdir(exist_ok=True)
    fig.savefig(primary_path, dpi=FIG_DPI, bbox_inches="tight")
    dest_name = fig_name if fig_name else primary_path.name
    fig.savefig(FIGURES_DIR / dest_name, dpi=FIG_DPI, bbox_inches="tight")
    rel = (FIGURES_DIR / dest_name).relative_to(BASE)
    print(f"[*] saved: {primary_path.name}  →  {rel}")

# ═══════════════════════════════════════════════════════════════════════
# データ読み込み
# ═══════════════════════════════════════════════════════════════════════

def read_lab_config():
    config_path = Path(__file__).resolve().parent.parent / "scripts" / "lab_config.sh"
    cfg = {}
    if not config_path.exists():
        return cfg
    for line in config_path.read_text().splitlines():
        m = re.match(r'^(\w+)="\$\{\w+:-(.+)\}"', line.strip())
        if m:
            cfg[m.group(1)] = m.group(2)
    return cfg

def load_csv_throughput(csv_path: Path, col_idx: int):
    raw = []
    for line in csv_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("time") or not line.strip():
            continue
        parts = line.split(",")
        if len(parts) <= col_idx:
            continue
        try:
            raw.append((float(parts[0]), int(parts[col_idx]) * 8 / 1e6))
        except (ValueError, IndexError):
            continue
    if not raw:
        return [], []

    # 時系列が混入している場合（複数モニタプロセスが同一CSVに書き込んだ場合）に対処:
    # 時刻でソートし、最大ギャップで2つのクラスタを分離して "現在の" 計測データのみを残す
    raw.sort(key=lambda x: x[0])
    times = [x[0] for x in raw]
    if len(times) >= 4:
        gaps = [times[i+1] - times[i] for i in range(len(times)-1)]
        max_gap = max(gaps)
        if max_gap > 50:  # 50秒以上のギャップ → 別計測のデータが混入
            split = gaps.index(max_gap)
            cluster1 = raw[:split+1]
            cluster2 = raw[split+1:]
            # 開始時刻が小さい（0に近い）クラスタを現在の計測とみなす
            raw = cluster1 if cluster1[0][0] <= cluster2[0][0] else cluster2

    t  = [x[0] for x in raw]
    mb = [x[1] for x in raw]
    return t, mb

def load_iperf_server_throughput(json_path: Path):
    raw = json_path.read_text(encoding="utf-8", errors="ignore")
    start_idx = raw.find("{")
    if start_idx > 0:
        raw = raw[start_idx:]
    d = json.loads(raw)
    intervals = d.get("intervals", [])
    recv_intervals = [itv for itv in intervals
                      if not itv.get("sum", {}).get("sender", True)]
    if recv_intervals:
        intervals = recv_intervals
    t, mbps = [], []
    for itv in intervals:
        s = itv.get("sum")
        if not s:
            streams = itv.get("streams", [])
            s = streams[0] if streams else None
        if not s:
            continue
        start_sec = s.get("start")
        bps = s.get("bits_per_second")
        if start_sec is None or bps is None:
            continue
        t.append(float(start_sec))
        mbps.append(float(bps) / 1e6)
    return t, mbps

PING_RE = re.compile(r"^\[(?P<ts>[0-9]+\.[0-9]+)\].*time=(?P<rtt>[0-9.]+)\s*ms")
OWD_RE  = re.compile(r"^\[(?P<ts>[0-9]+\.[0-9]+)\].*owd=(?P<owd>[0-9.]+)\s*ms")

def load_ping_rtt(log_path: Path):
    ts, rtt = [], []
    for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = PING_RE.match(line.strip())
        if not m:
            continue
        ts.append(float(m.group("ts")))
        rtt.append(float(m.group("rtt")))
    if not ts:
        return [], []
    t0 = ts[0]
    return [x - t0 for x in ts], rtt

def load_owd(log_path: Path):
    ts, owd = [], []
    for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = OWD_RE.match(line.strip())
        if not m:
            continue
        ts.append(float(m.group("ts")))
        owd.append(float(m.group("owd")))
    if not ts:
        return [], []
    t0 = ts[0]
    return [x - t0 for x in ts], owd

def load_owd_loss_rate(log_path: Path, probe_interval: float = 0.02,
                       window: float = 1.0, step: float = 0.2):
    seq_re = re.compile(r"\[([0-9]+\.[0-9]+)\].*seq=([0-9]+)")
    received: dict = {}
    t_start = None
    for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = seq_re.search(line)
        if not m:
            continue
        ts, seq = float(m.group(1)), int(m.group(2))
        if t_start is None:
            t_start = ts - (seq - 1) * probe_interval
        received[seq] = ts - t_start
    if not received:
        return [], []
    max_seq = max(received.keys())
    t_end = max_seq * probe_interval
    t_vals, loss_vals = [], []
    t = step
    while t <= t_end:
        seq_lo = max(1, round((t - window) / probe_interval) + 1)
        seq_hi = min(max_seq, round(t / probe_interval))
        n_exp = max(seq_hi - seq_lo + 1, 1)
        n_got = sum(1 for s in range(seq_lo, seq_hi + 1) if s in received)
        t_vals.append(t)
        loss_vals.append(max(0.0, (1.0 - n_got / n_exp) * 100.0))
        t += step
    return t_vals, loss_vals

def load_ping_loss_rate(log_path: Path, window: float = 3.0, step: float = 0.5,
                        ping_interval: float = 0.1):
    seq_re = re.compile(r'\[([0-9]+\.[0-9]+)\].*icmp_seq=([0-9]+)')
    received: dict = {}
    t_start = None
    for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = seq_re.search(line)
        if not m:
            continue
        ts, seq = float(m.group(1)), int(m.group(2))
        if t_start is None:
            t_start = ts - (seq - 1) * ping_interval
        received[seq] = ts - t_start
    if not received:
        return [], []
    max_seq = max(received.keys())
    t_end = max_seq * ping_interval
    t_vals, loss_vals = [], []
    t = step
    while t <= t_end:
        seq_lo = max(1, round((t - window) / ping_interval) + 1)
        seq_hi = min(max_seq, round(t / ping_interval))
        n_exp = max(seq_hi - seq_lo + 1, 1)
        n_got = sum(1 for s in range(seq_lo, seq_hi + 1) if s in received)
        t_vals.append(t)
        loss_vals.append(max(0.0, (1.0 - n_got / n_exp) * 100.0))
        t += step
    return t_vals, loss_vals

def find_file(outdir: Path, candidates):
    for name in candidates:
        p = outdir / name
        if p.exists():
            return p
    return None

def _parse_rate_mbps(rate_str: str) -> float:
    s = rate_str.strip().upper().rstrip("BIT").rstrip("B")
    if s.endswith("G"):
        return float(s[:-1]) * 1000
    if s.endswith("M"):
        return float(s[:-1])
    if s.endswith("K"):
        return float(s[:-1]) / 1000
    return float(s) / 1e6

def _baseline_mean(t_vals, mbps_vals, t_start=2, t_end=None):
    if t_end is None:
        t_end = FAILURE_START - 1
    vals = [v for tv, v in zip(t_vals, mbps_vals) if t_start <= tv <= t_end]
    return float(np.mean(vals)) if vals else None

def has_data(dirpath: Path) -> bool:
    """スループットまたはpingに実データがあるか"""
    thr = dirpath / "throughput.csv"
    if thr.exists():
        non_zero = sum(
            1 for line in thr.read_text(errors="ignore").splitlines()
            if not line.startswith("time") and line.strip()
            and not all(v.strip() == "0" for v in line.split(",")[1:])
        )
        if non_zero > 5:
            return True
    for _, _, _, tx, _ in PRIORITIES:
        ping = dirpath / f"{tx}_ping.log"
        if ping.exists() and PING_RE.search(ping.read_text(errors="ignore")):
            return True
    return False

# ═══════════════════════════════════════════════════════════════════════
# 描画ヘルパー
# ═══════════════════════════════════════════════════════════════════════

def add_failure_zone(ax, x_max=None, rsvp=False):
    if FAILURE_START is None:
        return
    ax.axvspan(FAILURE_START, FAILURE_END, alpha=0.08, color="red", zorder=0)
    ax.axvline(FAILURE_START, color="#d62728", linestyle="--", linewidth=1.1, alpha=0.7)
    ax.axvline(FAILURE_END,   color="#1f77b4", linestyle="--", linewidth=1.1, alpha=0.7)
    y_top = ax.get_ylim()[1]
    ax.text(FAILURE_START + 0.5, y_top * 0.97,
            "障害開始", color="#d62728", fontsize=9, va="top")
    ax.text(FAILURE_END + 0.5, y_top * 0.97,
            "障害回復", color="#1f77b4", fontsize=9, va="top")
    if rsvp and POLICE_DOWN is not None:
        ax.axvline(POLICE_DOWN, color="#E69F00", linestyle=":", linewidth=1.2, alpha=0.8)
        ax.axvline(POLICE_UP,   color="#009E73", linestyle=":", linewidth=1.2, alpha=0.8)
        ax.text(POLICE_DOWN + 0.3, y_top * 0.82,
                "Police\n2-link", color="#E69F00", fontsize=8, va="top")
        ax.text(POLICE_UP + 0.3, y_top * 0.82,
                "Police\n3-link", color="#009E73", fontsize=8, va="top")

# ═══════════════════════════════════════════════════════════════════════
# パケットロスグラフ (per-scenario)
# ═══════════════════════════════════════════════════════════════════════

_PING_SEQ_RE = re.compile(r'\[([0-9]+\.[0-9]+)\].*icmp_seq=([0-9]+)')

def _ping_total_loss_pct(ping_path: Path) -> float:
    """ping ログ全体のパケットロス率 (icmp_seq 欠番カウント)"""
    received, max_seq = set(), 0
    for line in ping_path.read_text(errors="ignore").splitlines():
        m = _PING_SEQ_RE.search(line)
        if m:
            seq = int(m.group(2))
            received.add(seq)
            max_seq = max(max_seq, seq)
    return max(0.0, (1.0 - len(received) / max_seq) * 100) if max_seq > 0 else 0.0


def _plot_packet_loss_ping(outdir: Path, scenario_title: str):
    """ping ログベースのパケロス棒グラフ (FRR シナリオ向け: packet_loss.csv がない場合)"""
    cls_map    = {"Tx1": "AF41(高)", "Tx2": "AF42(中)", "Tx3": "AF43(低)"}
    classes    = ["AF41(高)", "AF42(中)", "AF43(低)"]
    cls_labels = ["AF41\n(高優先)", "AF42\n(中優先)", "AF43\n(低優先)"]
    cls_colors = {"AF41(高)": "#0072B2", "AF42(中)": "#E69F00", "AF43(低)": "#009E73"}

    ping_loss: dict = {}
    for _, _, _, tx, _ in PRIORITIES:
        cls = cls_map[tx]
        ping_path = outdir / f"{tx}_ping.log"
        ping_loss[cls] = _ping_total_loss_pct(ping_path) if ping_path.exists() else 0.0

    cfg = read_lab_config()
    wrr_hi  = int(cfg.get("WRR_HI", "4"))
    wrr_me  = int(cfg.get("WRR_ME", "2"))
    wrr_lo  = int(cfg.get("WRR_LO", "1"))
    wrr_sum = wrr_hi + wrr_me + wrr_lo
    total_bw = sum(_parse_rate_mbps(cfg.get(k, "100M")) for k in ("CR1_BW", "CR2_BW", "CR3_BW"))
    wrr_targets = [
        total_bw * wrr_hi / wrr_sum,
        total_bw * wrr_me / wrr_sum,
        total_bw * wrr_lo / wrr_sum,
    ]

    e2e_ach: dict = {}
    rx_avg_map: dict = {}
    thr_csv = outdir / "throughput.csv"
    if thr_csv.exists():
        for col_idx, cls, target in zip([1, 2, 3], classes, wrr_targets):
            _, mbps_vals = load_csv_throughput(thr_csv, col_idx)
            if len(mbps_vals) > 4:
                mbps_vals = mbps_vals[1:-1]
            avg_rx = float(np.mean(mbps_vals)) if mbps_vals else 0.0
            e2e_ach[cls]    = min(100.0, avg_rx / target * 100) if target > 0 else 0.0
            rx_avg_map[cls] = avg_rx

    fig, axes = plt.subplots(1, 2, figsize=(10, 5))
    fig.suptitle(f"{scenario_title}  パケットロス率 (優先度別)",
                 fontsize=13, fontweight="bold")

    # パネル 1: E2E ping ロス率
    ax = axes[0]
    vals   = [ping_loss.get(c, 0.0) for c in classes]
    colors = [cls_colors[c] for c in classes]
    bars = ax.bar(cls_labels, vals, color=colors, edgecolor="white", width=0.5)
    for bar, v in zip(bars, vals):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.3, f"{v:.1f}%",
                ha="center", va="bottom", fontsize=9, fontweight="bold")
    ax.set_ylabel("Packet Loss (%)")
    ax.set_title("E2E パケットロス率\n(ping icmp_seq 欠番ベース)", fontsize=10)
    ax.set_ylim(0, max(max(vals) * 1.35, 5))
    ax.grid(axis="y")
    if all(v == 0 for v in vals):
        ax.text(0.5, 0.5, "ロスなし (0%)", transform=ax.transAxes,
                ha="center", va="center", fontsize=13, color="green", fontweight="bold")
    elif vals[0] < vals[1] < vals[2]:
        ax.text(0.5, 0.97, "✓ 優先制御 正常  (AF41 < AF42 < AF43)",
                transform=ax.transAxes, ha="center", va="top",
                fontsize=8, color="green", fontweight="bold")

    # パネル 2: WRR 達成率
    ax2 = axes[1]
    if e2e_ach:
        vals2   = [e2e_ach.get(c, 0.0)    for c in classes]
        rx_avgs = [rx_avg_map.get(c, 0.0) for c in classes]
        bars2 = ax2.bar(cls_labels, vals2, color=colors, edgecolor="white", width=0.5)
        for bar, v, rx in zip(bars2, vals2, rx_avgs):
            ax2.text(bar.get_x() + bar.get_width() / 2,
                     bar.get_height() + 0.5,
                     f"{v:.1f}%\n(Rx:{rx:.0f}M)",
                     ha="center", va="bottom", fontsize=9, fontweight="bold")
    tgt_label = "/".join(f"{t:.0f}M" for t in wrr_targets)
    ax2.set_ylabel("WRR 達成率 (%)")
    ax2.set_title(f"WRR 理論値達成率\n(目標: {tgt_label} = 100%)", fontsize=10)
    ax2.set_ylim(0, 100)
    ax2.axhline(100, color="black", linewidth=0.8, linestyle="--", alpha=0.5)
    ax2.grid(axis="y", alpha=0.3)

    fig.tight_layout()
    out = outdir / "Docker_packet_loss.png"
    _save(fig, out, f"{outdir.name}_packetloss.png")
    plt.close(fig)


def plot_packet_loss(outdir: Path, scenario_title: str):
    """packet_loss.csv + throughput.csv から優先度別ロス棒グラフ
    packet_loss.csv がない場合は ping ログでフォールバック (FRR シナリオ向け)"""
    csv_path = outdir / "packet_loss.csv"
    if not csv_path.exists():
        _plot_packet_loss_ping(outdir, scenario_title)
        return

    rows = []
    for line in csv_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("node") or not line.strip():
            continue
        parts = line.split(",")
        if len(parts) < 7:
            continue
        try:
            rows.append({
                "node":    parts[0], "iface": parts[1],
                "dir":     parts[2], "cls":   parts[3],
                "sent":    int(parts[4]), "dropped": int(parts[5]),
            })
        except ValueError:
            continue

    if not rows:
        return

    classes    = ["AF41(高)", "AF42(中)", "AF43(低)"]
    cls_colors = {
        "AF41(高)": "#0072B2",
        "AF42(中)": "#E69F00",
        "AF43(低)": "#009E73",
    }

    def aggregate(direction, node_filter=None):
        result = {}
        for cls in classes:
            matched = [r for r in rows
                       if r["cls"] == cls and r["dir"] == direction
                       and (node_filter is None or node_filter in r["node"])]
            total_sent    = sum(r["sent"]    for r in matched)
            total_dropped = sum(r["dropped"] for r in matched)
            total = total_sent + total_dropped
            result[cls] = {
                "sent": total_sent, "dropped": total_dropped,
                "loss": total_dropped / total * 100 if total > 0 else 0.0,
            }
        return result

    ler_eg = aggregate("egress", node_filter="LER_Ingress_ns")
    cr_eg  = aggregate("egress", node_filter="CoreRouter")

    cfg = read_lab_config()
    wrr_hi  = int(cfg.get("WRR_HI", "4"))
    wrr_me  = int(cfg.get("WRR_ME", "2"))
    wrr_lo  = int(cfg.get("WRR_LO", "1"))
    wrr_sum = wrr_hi + wrr_me + wrr_lo
    total_bw = sum(_parse_rate_mbps(cfg.get(k, "100M")) for k in ("CR1_BW", "CR2_BW", "CR3_BW"))
    wrr_targets = [
        total_bw * wrr_hi / wrr_sum,
        total_bw * wrr_me / wrr_sum,
        total_bw * wrr_lo / wrr_sum,
    ]
    e2e_loss = {}
    thr_csv = outdir / "throughput.csv"
    if thr_csv.exists():
        for col_idx, cls, target in zip([1, 2, 3], classes, wrr_targets):
            t_vals, mbps_vals = load_csv_throughput(thr_csv, col_idx)
            if len(mbps_vals) > 4:
                mbps_vals = mbps_vals[1:-1]
            avg_rx = float(np.mean(mbps_vals)) if mbps_vals else 0.0
            achieved = min(100.0, avg_rx / target * 100) if target > 0 else 0.0
            e2e_loss[cls] = {"avg_rx": avg_rx, "target": target, "achieved": achieved}

    n_panels = 3 if e2e_loss else 2
    fig, axes = plt.subplots(1, n_panels, figsize=(5 * n_panels, 5))
    fig.suptitle(f"{scenario_title}  パケットロス率 (優先度別)",
                 fontsize=13, fontweight="bold")

    cls_xlabels = ["AF41\n(高優先)", "AF42\n(中優先)", "AF43\n(低優先)"]

    def draw_bar(ax, data, title):
        vals   = [data[c]["loss"]    for c in classes]
        drops  = [data[c]["dropped"] for c in classes]
        colors = [cls_colors[c]      for c in classes]
        bars = ax.bar(cls_xlabels, vals, color=colors, edgecolor="white", width=0.5)
        for bar, v, d in zip(bars, vals, drops):
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 0.5,
                    f"{v:.1f}%\n({d:,} pkt)",
                    ha="center", va="bottom", fontsize=9, fontweight="bold")
        ax.set_ylabel("Packet Loss (%)")
        ax.set_title(title, fontsize=10)
        ax.set_ylim(0, max(vals) * 1.3 + 5 if max(vals) > 0 else 10)
        ax.grid(axis="y")
        if all(v == 0 for v in vals):
            ax.text(0.5, 0.5, "ロスなし (0%)", transform=ax.transAxes,
                    ha="center", va="center", fontsize=13, color="green",
                    fontweight="bold")
        elif vals[0] < vals[1] < vals[2]:
            ax.text(0.5, 0.97, "✓ 優先制御 正常  (AF41 < AF42 < AF43)",
                    transform=ax.transAxes, ha="center", va="top",
                    fontsize=8, color="green", fontweight="bold")

    draw_bar(axes[0], ler_eg, "LER_Ingress HTB/WRR\n(輻輳時ドロップ率)")
    draw_bar(axes[1], cr_eg,  "CoreRouter HTB\n(中継ドロップ率)")

    if e2e_loss:
        ax = axes[2]
        vals   = [e2e_loss[c]["achieved"] for c in classes]
        rx_avg = [e2e_loss[c]["avg_rx"]   for c in classes]
        colors = [cls_colors[c]           for c in classes]
        bars = ax.bar(cls_xlabels, vals, color=colors, edgecolor="white", width=0.5)
        for bar, v, rx in zip(bars, vals, rx_avg):
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 0.5,
                    f"{v:.1f}%\n(Rx:{rx:.0f}M)",
                    ha="center", va="bottom", fontsize=9, fontweight="bold")
        tgt_label = "/".join(f"{t:.0f}M" for t in wrr_targets)
        ax.set_ylabel("WRR 達成率 (%)")
        ax.set_title(f"WRR 理論値達成率\n(目標: {tgt_label} = 100%)", fontsize=10)
        ax.set_ylim(0, 100)
        ax.axhline(100, color="black", linewidth=0.8, linestyle="--", alpha=0.5)
        ax.grid(axis="y")

    fig.tight_layout()
    out = outdir / "Docker_packet_loss.png"
    _save(fig, out, f"{outdir.name}_packetloss.png")
    plt.close(fig)

# ═══════════════════════════════════════════════════════════════════════
# シナリオ別グラフ生成
# ═══════════════════════════════════════════════════════════════════════

def main(outdir: Path):
    # シナリオ情報を SCENARIOS / FRR_SCENARIOS から取得
    sc_info = next((s for s in SCENARIOS + FRR_SCENARIOS if s[0] == outdir.name), None)
    if sc_info:
        _, sc_label, _, _, is_failure = sc_info
    else:
        sc_label   = outdir.name
        is_failure = outdir.name not in ("normal",)
    is_failure_rsvp = "rsvp" in outdir.name.lower()

    thr_data = []   # (label, t, mbps, color)
    dly_data = []   # (label, t, rtt, t_loss, loss, color)
    owd_data = []   # (label, t, owd, t_loss, loss, color)

    csv_path = outdir / "throughput.csv"

    for pri_label, pri_color, col, tx, rx in PRIORITIES:
        ping_candidates = [f"{tx}_ping.log", f"{tx.lower()}_ping.log",
                           f"{tx}.log", f"{tx.lower()}.log"]

        # スループット: CSV 優先 → iperf3 JSON にフォールバック
        if csv_path.exists():
            t, mbps = load_csv_throughput(csv_path, col)
            if t:
                thr_data.append((pri_label, t, mbps, pri_color))
        else:
            iperf_json = find_file(outdir, [f"{rx}_server.json", f"{rx.lower()}_server.json"])
            if iperf_json:
                try:
                    t, mbps = load_iperf_server_throughput(iperf_json)
                    thr_data.append((pri_label, t, mbps, pri_color))
                except Exception as e:
                    print(f"[!] iperf JSON 読み込み失敗 ({rx}): {e}")

        # ping RTT
        ping_log = find_file(outdir, ping_candidates)
        if ping_log:
            t, rtt     = load_ping_rtt(ping_log)
            t_loss, loss = load_ping_loss_rate(ping_log)
            if t:
                dly_data.append((pri_label, t, rtt, t_loss, loss, pri_color))

        # OWD
        owd_log = find_file(outdir, [f"{tx}_owd.log", f"{tx.lower()}_owd.log"])
        if owd_log:
            t_owd, owd = load_owd(owd_log)
            t_oloss, oloss = load_owd_loss_rate(owd_log)
            if t_owd:
                owd_data.append((pri_label, t_owd, owd, t_oloss, oloss, pri_color))

    # パケットロス棒グラフ
    plot_packet_loss(outdir, sc_label)

    # ── スループット ──────────────────────────────────────────────────
    if thr_data:
        fig, ax = plt.subplots(figsize=(10, 5))
        for label, t, mbps, color in thr_data:
            ax.plot(t, mbps, label=label, color=color)
        ax.set_xlim(THR_X_MIN, THR_X_MAX)
        ax.set_ylim(bottom=THR_Y_MIN, top=THR_Y_MAX)
        if is_failure:
            add_failure_zone(ax, THR_X_MAX, rsvp=is_failure_rsvp)
        ax.set_title(f"{sc_label}  スループット (iperf3 UDP 受信)")
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Throughput (Mbit/s)")
        ax.legend(loc="lower right")
        ax.grid(True, axis="y")
        fig.tight_layout()
        out = outdir / "Docker_all_throughput.png"
        _save(fig, out, f"{outdir.name}_throughput.png")
        plt.close(fig)

    # ── 遅延 (ping RTT) ────────────────────────────────────────────────
    if dly_data:
        def _plot_delay(ax, y_top=None, title_suffix=""):
            ax2 = ax.twinx() if SHOW_LOSS else None
            for label, t, rtt, t_loss, loss, color in dly_data:
                ax.plot(t, rtt, label=label, color=color, alpha=0.85)
                if ax2 and t_loss:
                    ax2.fill_between(t_loss, loss, step="post", color=color,
                                     alpha=0.15, linewidth=0)
                    ax2.step(t_loss, loss, where="post", color=color, linestyle=":",
                             linewidth=1.0, alpha=0.7)
            ax.set_xlim(DLY_X_MIN, DLY_X_MAX)
            ax.set_ylim(bottom=DLY_Y_MIN, top=y_top)
            if ax2:
                ax2.set_ylim(0, 105)
                ax2.set_ylabel("Loss (%)", fontsize=9)
                ax2.tick_params(labelsize=8)
            if is_failure:
                add_failure_zone(ax, DLY_X_MAX, rsvp=is_failure_rsvp)
            ax.set_title(f"{sc_label}  エンドツーエンド遅延 (ping RTT){title_suffix}")
            ax.set_xlabel("Time (s)")
            ax.set_ylabel("RTT (ms)")
            h1, l1 = ax.get_legend_handles_labels()
            h2, l2 = ax2.get_legend_handles_labels() if ax2 else ([], [])
            ax.legend(h1 + h2, l1 + l2, fontsize=9 if not ax2 else 8,
                      loc="upper right")
            ax.grid(True, axis="y")

        fig, ax = plt.subplots(figsize=(10, 5))
        _plot_delay(ax)
        out = outdir / "Docker_all_delay_rtt.png"
        _save(fig, out, f"{outdir.name}_delay_rtt.png")
        plt.close(fig)

        all_rtt = [v for _, _, rtt, *_ in dly_data for v in rtt]
        if all_rtt:
            zoom_top = (float(np.percentile(all_rtt, 95)) * 1.2
                        if DLY_Y_ZOOM == "auto" else float(DLY_Y_ZOOM))
            fig, ax = plt.subplots(figsize=(10, 5))
            _plot_delay(ax, y_top=zoom_top,
                        title_suffix=f"  [95th-pct clip ≤{zoom_top:.0f}ms]")
            out_z = outdir / "Docker_all_delay_rtt_zoom.png"
            _save(fig, out_z, f"{outdir.name}_delay_rtt_zoom.png")
            plt.close(fig)

    # ── OWD (片道遅延) ─────────────────────────────────────────────────
    if owd_data:
        def _plot_owd(ax, y_top=None, title_suffix=""):
            ax2 = ax.twinx() if SHOW_LOSS else None
            for label, t, owd, t_loss, loss, color in owd_data:
                ax.plot(t, owd, label=label, color=color, alpha=0.85, linewidth=1.4)
                if ax2 and t_loss:
                    ax2.fill_between(t_loss, loss, step="post", color=color,
                                     alpha=0.15, linewidth=0)
                    ax2.step(t_loss, loss, where="post", color=color, linestyle=":",
                             linewidth=1.0, alpha=0.7)
            ax.set_xlim(DLY_X_MIN, DLY_X_MAX)
            ax.set_ylim(bottom=0, top=y_top)
            if ax2:
                ax2.set_ylim(0, 105)
                ax2.set_ylabel("Loss (%)", fontsize=9)
                ax2.tick_params(labelsize=8)
            if is_failure:
                add_failure_zone(ax, DLY_X_MAX, rsvp=is_failure_rsvp)
            ax.set_title(
                f"{sc_label}  片道遅延 OWD (UDP プローブ, DSCP マーク){title_suffix}")
            ax.set_xlabel("Time (s)")
            ax.set_ylabel("OWD (ms)")
            h1, l1 = ax.get_legend_handles_labels()
            h2, l2 = ax2.get_legend_handles_labels() if ax2 else ([], [])
            ax.legend(h1 + h2, l1 + l2, fontsize=9 if not ax2 else 8,
                      loc="upper right")
            ax.grid(True, axis="y")

        fig, ax = plt.subplots(figsize=(10, 5))
        _plot_owd(ax)
        out_owd = outdir / "Docker_all_owd.png"
        _save(fig, out_owd, f"{outdir.name}_owd.png")
        plt.close(fig)

        all_owd_vals = [v for _, _, owd, *_ in owd_data for v in owd]
        if all_owd_vals:
            zoom_top = float(np.percentile(all_owd_vals, 95)) * 1.3
            fig, ax = plt.subplots(figsize=(10, 5))
            _plot_owd(ax, y_top=zoom_top,
                      title_suffix=f"  [95th-pct clip ≤{zoom_top:.1f}ms]")
            out_z = outdir / "Docker_all_owd_zoom.png"
            _save(fig, out_z, f"{outdir.name}_owd_zoom.png")
            plt.close(fig)

# ═══════════════════════════════════════════════════════════════════════
# シナリオ比較グラフ (優先度別3行レイアウト)
# ═══════════════════════════════════════════════════════════════════════

def _active_scenarios(base_dir: Path):
    """データが存在するシナリオを返す。凡例名が同じ場合は先に見つかった方を使う。"""
    seen, result = set(), []
    for d, n, c, ls, f in SCENARIOS:
        if n in seen:
            continue
        if (base_dir / d).exists() and has_data(base_dir / d):
            seen.add(n)
            result.append((d, n, c, ls, f))
    return result


def compare_throughput_priority(base_dir: Path):
    """スループット比較: 3行=優先度クラス × 全シナリオ重ね描き"""
    active = _active_scenarios(base_dir)
    if not active:
        print("[skip] compare_throughput_priority: データなし")
        return

    fig, axes = plt.subplots(3, 1, figsize=(11, 11), sharex=True)
    fig.suptitle("スループット比較 (優先度クラス別)",
                 fontsize=14, fontweight="bold")

    for ax, (pri_label, pri_color, col, tx, rx) in zip(axes, PRIORITIES):
        for dirname, sc_name, sc_color, ls, is_fail in active:
            t, mbps = load_csv_throughput(base_dir / dirname / "throughput.csv", col) \
                if (base_dir / dirname / "throughput.csv").exists() else ([], [])
            if not t:
                continue
            ax.plot(t, mbps, label=sc_name, color=sc_color, linestyle=ls, linewidth=1.8)

        ax.axvspan(FAILURE_START, FAILURE_END, alpha=0.07, color="red", zorder=0)
        ax.axvline(FAILURE_START, color="#d62728", linestyle="--", lw=1.1, alpha=0.7)
        ax.axvline(FAILURE_END,   color="#1f77b4", linestyle="--", lw=1.1, alpha=0.7)
        ax.set_xlim(0, THR_X_MAX)
        ax.set_ylim(bottom=0)
        ax.set_title(f"● {pri_label}", color=pri_color, fontweight="bold", fontsize=12)
        ax.set_ylabel("Throughput (Mbit/s)")
        ax.legend(loc="lower right", fontsize=9)
        ax.grid(True, axis="y")

    axes[0].text(FAILURE_START + 0.3, axes[0].get_ylim()[1] * 0.96,
                 "障害開始", color="#d62728", fontsize=8, va="top")
    axes[0].text(FAILURE_END + 0.3, axes[0].get_ylim()[1] * 0.96,
                 "障害回復", color="#1f77b4", fontsize=8, va="top")
    axes[-1].set_xlabel("Time (s)")
    fig.tight_layout()
    out = base_dir / "compare_throughput_priority.png"
    _save(fig, out)
    plt.close(fig)


def compare_delay_priority(base_dir: Path):
    """遅延比較: 3行=優先度クラス × 全シナリオ重ね描き (OWD優先, なければping RTT)"""
    active = _active_scenarios(base_dir)
    if not active:
        print("[skip] compare_delay_priority: データなし")
        return

    fig, axes = plt.subplots(3, 1, figsize=(11, 11), sharex=True)
    fig.suptitle("エンドツーエンド遅延比較 (優先度クラス別)",
                 fontsize=14, fontweight="bold")
    ylabel = "ms"

    for ax, (pri_label, pri_color, col, tx, rx) in zip(axes, PRIORITIES):
        all_vals = []
        for dirname, sc_name, sc_color, ls, _ in active:
            owd_path  = base_dir / dirname / f"{tx}_owd.log"
            ping_path = base_dir / dirname / f"{tx}_ping.log"
            if owd_path.exists():
                t, vals = load_owd(owd_path)
                ylabel = "OWD (ms)"
            elif ping_path.exists():
                t, vals = load_ping_rtt(ping_path)
                ylabel = "RTT (ms)"
            else:
                continue
            if not t:
                continue
            ax.plot(t, vals, label=sc_name, color=sc_color, linestyle=ls,
                    linewidth=1.4, alpha=0.85)
            all_vals.extend(vals)

        if all_vals:
            p95 = float(np.percentile(all_vals, 95)) * 1.3
            ax.set_ylim(bottom=0, top=p95)
        ax.axvspan(FAILURE_START, FAILURE_END, alpha=0.07, color="red", zorder=0)
        ax.axvline(FAILURE_START, color="#d62728", linestyle="--", lw=1.1, alpha=0.7)
        ax.axvline(FAILURE_END,   color="#1f77b4", linestyle="--", lw=1.1, alpha=0.7)
        ax.set_xlim(0, DLY_X_MAX)
        ax.set_title(f"● {pri_label}", color=pri_color, fontweight="bold", fontsize=12)
        ax.set_ylabel(ylabel)
        ax.legend(loc="upper right", fontsize=9)
        ax.grid(True, axis="y")

    axes[0].text(FAILURE_START + 0.3, axes[0].get_ylim()[1] * 0.96,
                 "障害開始", color="#d62728", fontsize=8, va="top")
    axes[0].text(FAILURE_END + 0.3, axes[0].get_ylim()[1] * 0.96,
                 "障害回復", color="#1f77b4", fontsize=8, va="top")
    axes[-1].set_xlabel("Time (s)")
    fig.tight_layout()
    out = base_dir / "compare_delay_priority.png"
    _save(fig, out)
    plt.close(fig)


def compare_scenarios(base_dir: Path):
    """スループット絶対値 + ベースライン正規化比較 (3行=優先度)"""
    active = _active_scenarios(base_dir)
    if not active:
        return

    rx_labels  = [pri for pri, *_ in PRIORITIES]
    rx_indices  = [col for _, _, col, *_ in PRIORITIES]

    fig1, axes1 = plt.subplots(3, 1, figsize=(11, 12), sharex=True)
    fig1.suptitle("シナリオ比較  スループット (絶対値)", fontsize=13)
    fig2, axes2 = plt.subplots(3, 1, figsize=(11, 12), sharex=True)
    fig2.suptitle(
        "シナリオ比較  スループット (ベースライン正規化)\n"
        "ECMPハッシュのばらつきを除去 — 真のQoS効果を表示",
        fontsize=12,
    )

    for ax1, ax2, rx_idx, rx_label in zip(axes1, axes2, rx_indices, rx_labels):
        for dirname, sc_name, color, ls, is_fail in active:
            csv_path = base_dir / dirname / "throughput.csv"
            if not csv_path.exists():
                continue
            t, mbps = load_csv_throughput(csv_path, rx_idx)
            if not t:
                continue
            ax1.plot(t, mbps, label=sc_name, color=color, linestyle=ls, linewidth=1.8)
            if not is_fail:
                ax2.axhline(100, color=color, linestyle=ls, linewidth=1.2,
                            alpha=0.6, label=sc_name)
            else:
                base = _baseline_mean(t, mbps)
                if base and base > 0:
                    norm = [v / base * 100 for v in mbps]
                    ax2.plot(t, norm, label=f"{sc_name} (base={base:.0f}M)",
                             color=color, linestyle=ls, linewidth=1.8)

        for ax in (ax1, ax2):
            ax.axvspan(FAILURE_START, FAILURE_END, alpha=0.07, color="red", zorder=0)
            ax.axvline(FAILURE_START, color="#d62728", linestyle="--", lw=1.1, alpha=0.7)
            ax.axvline(FAILURE_END,   color="#1f77b4", linestyle="--", lw=1.1, alpha=0.7)
            ax.set_xlim(0, THR_X_MAX)
            ax.set_title(rx_label)
            ax.legend(fontsize=9)
            ax.grid(True, axis="y")
        ax1.set_ylabel("Throughput (Mbit/s)")
        ax2.set_ylabel("Throughput (% of pre-failure baseline)")

    for axes in (axes1, axes2):
        axes[0].text(FAILURE_START + 0.3, axes[0].get_ylim()[1] * 0.97,
                     "障害開始", color="#d62728", fontsize=7, va="top")
        axes[0].text(FAILURE_END + 0.3, axes[0].get_ylim()[1] * 0.97,
                     "障害回復", color="#1f77b4", fontsize=7, va="top")
        axes[-1].set_xlabel("Time (s)")

    fig1.tight_layout()
    out1 = base_dir / "compare_all_scenarios.png"
    _save(fig1, out1)
    plt.close(fig1)

    fig2.tight_layout()
    out2 = base_dir / "compare_normalized.png"
    _save(fig2, out2)
    plt.close(fig2)

    # 障害区間スループット低下率バーチャート
    _bar_data = {}
    for dirname, sc_name, color, ls, is_fail in active:
        if not is_fail:
            continue
        csv_path = base_dir / dirname / "throughput.csv"
        if not csv_path.exists():
            continue
        drops = []
        for _, _, rx_idx, *_ in PRIORITIES:
            t, mbps = load_csv_throughput(csv_path, rx_idx)
            base = _baseline_mean(t, mbps)
            fail = _baseline_mean(t, mbps, t_start=FAILURE_START + 1, t_end=FAILURE_END - 1)
            drops.append((1.0 - fail / base) * 100 if base and base > 0 and fail is not None else 0.0)
        _bar_data[sc_name] = (color, drops)

    if _bar_data:
        cls_names = [pri.replace(" (", "\n(") for pri, *_ in PRIORITIES]
        x = np.arange(len(cls_names))
        width = 0.7 / max(len(_bar_data), 1)
        offsets = [(i - (len(_bar_data) - 1) / 2) * width
                   for i in range(len(_bar_data))]
        fig3, ax3 = plt.subplots(figsize=(8, 5))
        for i, (sc_name, (color, drops)) in enumerate(_bar_data.items()):
            bars = ax3.bar(x + offsets[i], drops, width, label=sc_name,
                           color=color, alpha=0.8, edgecolor="white")
            for bar, v in zip(bars, drops):
                ax3.text(bar.get_x() + bar.get_width() / 2,
                         bar.get_height() + 0.5,
                         f"{v:.1f}%", ha="center", va="bottom", fontsize=9)
        ax3.set_xticks(x)
        ax3.set_xticklabels(cls_names)
        ax3.set_ylabel("スループット低下率 (%)")
        ax3.set_title(
            "障害区間における優先度クラス別スループット低下率\n"
            "(障害前ベースライン比, t=20-40s)",
            fontsize=12,
        )
        ax3.legend(fontsize=9)
        ax3.grid(axis="y")
        all_drops = [v for _, (_, drops) in _bar_data.items() for v in drops]
        ax3.set_ylim(0, max(max(all_drops) * 1.3, 10) + 5)
        ax3.text(0.98, 0.98,
                 "理想: AF41 < AF42 < AF43\n(高優先ほど低下率小)",
                 transform=ax3.transAxes, ha="right", va="top",
                 fontsize=8, color="gray",
                 bbox=dict(boxstyle="round", fc="white", alpha=0.7))
        fig3.tight_layout()
        out3 = base_dir / "compare_priority_drop.png"
        _save(fig3, out3)
        plt.close(fig3)


def compare_delay(base_dir: Path):
    """遅延比較 (全体図 + ズーム図, 3行=優先度)"""
    active = _active_scenarios(base_dir)
    if not active:
        return

    all_data = [[] for _ in PRIORITIES]

    for dirname, sc_name, color, ls, _ in active:
        for i, (_, _, _, tx, rx) in enumerate(PRIORITIES):
            owd_path  = base_dir / dirname / f"{tx}_owd.log"
            ping_path = base_dir / dirname / f"{tx}_ping.log"
            if owd_path.exists():
                t, val = load_owd(owd_path)
                t_loss, loss = load_owd_loss_rate(owd_path)
            elif ping_path.exists():
                t, val = load_ping_rtt(ping_path)
                t_loss, loss = load_ping_loss_rate(ping_path)
            else:
                continue
            if t:
                all_data[i].append((t, val, t_loss, loss, sc_name, color, ls))

    has_owd = any(
        (base_dir / d / f"{tx}_owd.log").exists()
        for d, *_ in active for _, _, _, tx, _ in PRIORITIES
    )
    metric_label = "OWD (片道遅延)" if has_owd else "ping RTT"

    def _draw(ax, entries, y_top=None):
        ax2 = ax.twinx() if SHOW_LOSS else None
        for t, rtt, t_loss, loss, sc_name, color, ls in entries:
            ax.plot(t, rtt, label=sc_name, color=color, linestyle=ls,
                    linewidth=1.4, alpha=0.85)
            if ax2 and t_loss:
                ax2.fill_between(t_loss, loss, step="post", color=color,
                                 alpha=0.15, linewidth=0)
                ax2.step(t_loss, loss, where="post", color=color, linestyle=":",
                         linewidth=1.0, alpha=0.7)
        ax.axvspan(FAILURE_START, FAILURE_END, alpha=0.06, color="red", zorder=0)
        ax.axvline(FAILURE_START, color="#d62728",   linestyle="--", lw=1.1, alpha=0.7)
        ax.axvline(FAILURE_END,   color="#1f77b4",  linestyle="--", lw=1.1, alpha=0.7)
        ax.set_xlim(DLY_X_MIN, DLY_X_MAX)
        if y_top:
            ax.set_ylim(bottom=0, top=y_top)
        if ax2:
            ax2.set_ylim(0, 105)
            ax2.set_ylabel("Loss (%)", fontsize=9)
            ax2.tick_params(labelsize=8)
        ax.set_ylabel("ms")
        h1, l1 = ax.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels() if ax2 else ([], [])
        ax.legend(h1 + h2, l1 + l2, fontsize=8, loc="upper left", framealpha=0.85)
        ax.grid(True, axis="y")

    for suffix, use_zoom, out_name in [
        ("", False, "compare_delay.png"),
        ("  [95th-pct clip]", True, "compare_delay_zoom.png"),
    ]:
        fig, axes = plt.subplots(3, 1, figsize=(11, 12), sharex=True)
        fig.suptitle(f"シナリオ比較  エンドツーエンド遅延 / {metric_label}{suffix}",
                     fontsize=13, fontweight="bold")
        for ax, (pri_label, pri_color, _, tx, _), entries in zip(axes, PRIORITIES, all_data):
            zoom_top = None
            if use_zoom and entries:
                per_p95 = [float(np.percentile(rtt, 95)) for _, rtt, *_ in entries if rtt]
                zoom_top = max(per_p95) * 1.3 if per_p95 else None
            _draw(ax, entries, y_top=zoom_top)
            ax.set_title(f"● {pri_label}", color=pri_color, fontweight="bold", fontsize=12)

        axes[0].text(FAILURE_START + 0.3, axes[0].get_ylim()[1] * 0.97,
                     "障害開始", color="#d62728", fontsize=7, va="top")
        axes[0].text(FAILURE_END + 0.3, axes[0].get_ylim()[1] * 0.97,
                     "障害回復", color="#1f77b4", fontsize=7, va="top")
        axes[-1].set_xlabel("Time (s)")
        fig.tight_layout()
        out = base_dir / out_name
        _save(fig, out)
        plt.close(fig)


def compare_packet_loss(base_dir: Path):
    """パケットロス比較棒グラフ (3パネル: LER / CoreRouter / WRR達成率)"""
    active = _active_scenarios(base_dir)
    if not active:
        return

    cfg = read_lab_config()
    wrr_hi  = int(cfg.get("WRR_HI", "4"))
    wrr_me  = int(cfg.get("WRR_ME", "2"))
    wrr_lo  = int(cfg.get("WRR_LO", "1"))
    wrr_sum = wrr_hi + wrr_me + wrr_lo
    total_bw = sum(_parse_rate_mbps(cfg.get(k, "100M")) for k in ("CR1_BW", "CR2_BW", "CR3_BW"))
    wrr_targets_mbps = [
        total_bw * wrr_hi / wrr_sum,
        total_bw * wrr_me / wrr_sum,
        total_bw * wrr_lo / wrr_sum,
    ]
    classes = ["AF41(高)", "AF42(中)", "AF43(低)"]

    def load_loss(dirname):
        csv_path = base_dir / dirname / "packet_loss.csv"
        if not csv_path.exists():
            return None, None, None
        rows = []
        for line in csv_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("node") or not line.strip():
                continue
            parts = line.split(",")
            if len(parts) < 7:
                continue
            try:
                rows.append({"node": parts[0], "iface": parts[1], "dir": parts[2],
                             "cls": parts[3], "sent": int(parts[4]), "dropped": int(parts[5])})
            except ValueError:
                continue

        def agg(direction, node_filter=None):
            result = {}
            for cls in classes:
                matched = [r for r in rows if r["cls"] == cls and r["dir"] == direction
                           and (node_filter is None or node_filter in r["node"])]
                sent = sum(r["sent"] for r in matched)
                dropped = sum(r["dropped"] for r in matched)
                total = sent + dropped
                result[cls] = dropped / total * 100 if total > 0 else 0.0
            return result

        ler = agg("egress", "LER_Ingress_ns")
        cr  = agg("egress", "CoreRouter")
        thr_csv = base_dir / dirname / "throughput.csv"
        e2e = {}
        if thr_csv.exists():
            for col_idx, cls, target in zip([1, 2, 3], classes, wrr_targets_mbps):
                t_vals, mbps_vals = load_csv_throughput(thr_csv, col_idx)
                if len(mbps_vals) > 4:
                    mbps_vals = mbps_vals[1:-1]
                avg_rx = float(np.mean(mbps_vals)) if mbps_vals else 0.0
                e2e[cls] = min(100.0, avg_rx / target * 100) if target > 0 else 0.0
        return ler, cr, e2e

    panel_data = []
    for dirname, sc_name, color, ls, _ in active:
        ler, cr, e2e = load_loss(dirname)
        if ler is not None:
            panel_data.append((sc_name, color, ler, cr, e2e))

    if not panel_data:
        return

    cls_xlabels = ["AF41\n(高優先)", "AF42\n(中優先)", "AF43\n(低優先)"]
    x = np.arange(len(classes))
    n_bars = len(panel_data)
    width  = 0.65 / max(n_bars, 1)
    offsets = [(i - (n_bars - 1) / 2) * width for i in range(n_bars)]

    tgt_label = "/".join(f"{t:.0f}M" for t in wrr_targets_mbps)
    panel_cfgs = [
        ("ler", "LER_Ingress HTB/WRR\n(輻輳ドロップ率)", False),
        ("cr",  "CoreRouter HTB\n(中継ドロップ率)", False),
        ("e2e", f"WRR 理論値達成率\n(目標: {tgt_label} = 100%)", True),
    ]

    fig, axes = plt.subplots(1, 3, figsize=(15, 6))
    fig.suptitle("シナリオ比較  パケットロス率 / WRR達成率 (優先度クラス別)",
                 fontsize=13, fontweight="bold")

    for ax, (key, title, is_achievement) in zip(axes, panel_cfgs):
        max_val = 0
        for i, (sc_name, color, ler, cr, e2e) in enumerate(panel_data):
            data = {"ler": ler, "cr": cr, "e2e": e2e}[key]
            vals = [data.get(c, 0.0) for c in classes]
            bars = ax.bar(x + offsets[i], vals, width,
                          label=sc_name, color=color, alpha=0.82, edgecolor="white")
            for bar, v in zip(bars, vals):
                fmt = f"{v:.1f}%"
                ax.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + 0.3,
                        fmt, ha="center", va="bottom", fontsize=8)
            max_val = max(max_val, max(vals))
        ax.set_xticks(x)
        ax.set_xticklabels(cls_xlabels)
        ax.set_title(title, fontsize=10)
        if is_achievement:
            ax.set_ylabel("達成率 (%)")
            ax.set_ylim(0, 100)
            ax.axhline(100, color="black", linewidth=0.8, linestyle="--", alpha=0.5)
            ax.legend(fontsize=9, loc="lower left")
        else:
            ax.set_ylabel("Packet Loss (%)")
            ax.set_ylim(0, max(max_val * 1.35, 5))
            ax.legend(fontsize=9, loc="upper left")
        ax.grid(axis="y")

    fig.tight_layout()
    out = base_dir / "compare_packet_loss.png"
    _save(fig, out)
    plt.close(fig)


def compare_rsvp_versions(base_dir: Path):
    """RSVP-TE v1 vs v2 詳細比較 (スループット・遅延・ズーム)"""
    versions = [
        ("failure_rsvp_v1", "RSVP-TE v1 (RTT計測)",  "#E69F00",  "--"),
        ("failure_rsvp_v2", "RSVP-TE v2 (OWD計測)",  "#1f77b4",  "-"),
    ]
    versions = [(d, n, c, ls) for d, n, c, ls in versions
                if (base_dir / d).exists() and has_data(base_dir / d)]
    if len(versions) < 2:
        return

    thr_data = {v[0]: [] for v in versions}
    dly_data = {v[0]: [] for v in versions}

    for dirname, _, _, _ in versions:
        csv_path = base_dir / dirname / "throughput.csv"
        for i, (pri_label, pri_color, col, tx, rx) in enumerate(PRIORITIES):
            if csv_path.exists():
                t, mbps = load_csv_throughput(csv_path, col)
                if t:
                    thr_data[dirname].append((pri_label, t, mbps, pri_color))
            log = find_file(base_dir / dirname,
                            [f"{tx}_owd.log", f"{tx}_ping.log"])
            if log:
                if log.name.endswith("owd.log"):
                    t, val = load_owd(log)
                else:
                    t, val = load_ping_rtt(log)
                if t:
                    dly_data[dirname].append((pri_label, t, val, pri_color))

    # スループット比較 (3行2列)
    fig, axes = plt.subplots(3, 2, figsize=(13, 11), sharex="col")
    fig.suptitle("RSVP-TE v1 vs v2  スループット比較",
                 fontsize=13, fontweight="bold")

    for row, (pri_label, pri_color, _, tx, _) in enumerate(PRIORITIES):
        for col, (dirname, sc_name, sc_color, ls) in enumerate(versions):
            ax = axes[row][col]
            entries = thr_data.get(dirname, [])
            if row < len(entries):
                _, t, mbps, _ = entries[row]
                ax.plot(t, mbps, color=pri_color, linestyle=ls, linewidth=1.8)
            ax.axvspan(FAILURE_START, FAILURE_END, alpha=0.08, color="red", zorder=0)
            ax.axvline(FAILURE_START, color="#d62728",   linestyle="--", lw=1.1, alpha=0.7)
            ax.axvline(FAILURE_END,   color="#1f77b4", linestyle="--", lw=1.1, alpha=0.7)
            ax.set_xlim(0, THR_X_MAX)
            ax.set_ylim(bottom=0)
            ax.set_title(f"{sc_name}\n{pri_label}", fontsize=9, color=pri_color)
            ax.set_ylabel("Throughput (Mbit/s)")
            ax.grid(True, axis="y")
            if row == 2:
                ax.set_xlabel("Time (s)")

    fig.tight_layout()
    out = base_dir / "compare_rsvp_versions_thr.png"
    _save(fig, out)
    plt.close(fig)

    # 遅延比較 (3行1列, 重ね描き + ズーム)
    for suffix, use_zoom, out_name in [
        ("", False, "compare_rsvp_versions_delay.png"),
        ("  [95th-pct clip]", True, "compare_rsvp_versions_delay_zoom.png"),
    ]:
        fig, axes = plt.subplots(3, 1, figsize=(11, 11), sharex=True)
        fig.suptitle(f"RSVP-TE v1 vs v2  遅延比較{suffix}\n(ITU-T G.8031 目標: <50ms)",
                     fontsize=13, fontweight="bold")

        for ax, (pri_label, pri_color, _, tx, _), in zip(axes, PRIORITIES):
            all_rtt = []
            for dirname, sc_name, sc_color, ls in versions:
                entries = dly_data.get(dirname, [])
                matched = [e for e in entries if tx in e[0] or pri_label == e[0]]
                if not matched:
                    continue
                _, t, val, _ = matched[0]
                ax.plot(t, val, label=sc_name, color=sc_color, linestyle=ls,
                        linewidth=1.4, alpha=0.85)
                all_rtt.extend(val)

            ax.axhline(50, color="red", linestyle=":", linewidth=1.5, alpha=0.8,
                       label="ITU-T G.8031  50ms")
            ax.axvspan(FAILURE_START, FAILURE_END, alpha=0.07, color="red", zorder=0)
            ax.axvline(FAILURE_START, color="#d62728",   linestyle="--", lw=1.1, alpha=0.7)
            ax.axvline(FAILURE_END,   color="#1f77b4", linestyle="--", lw=1.1, alpha=0.7)
            ax.set_xlim(DLY_X_MIN, DLY_X_MAX)
            if use_zoom and all_rtt:
                ax.set_ylim(bottom=0, top=float(np.percentile(all_rtt, 95)) * 1.3)
            ax.set_ylabel("ms")
            ax.set_title(f"● {pri_label}", color=pri_color, fontweight="bold", fontsize=12)
            ax.legend(fontsize=9)
            ax.grid(True, axis="y")

        axes[-1].set_xlabel("Time (s)")
        fig.tight_layout()
        out = base_dir / out_name
        _save(fig, out)
        plt.close(fig)

def compare_rsvp_effect(base_dir: Path):
    """RSVPの効果を強調した比較グラフ

    failure vs failure_rsvp を重ね描きし、RSVPが回復したトラフィック量を
    塗りつぶし領域で可視化する。normal をグレー破線で参照ラインとして追加。
    優先度クラス別3行レイアウト。
    """
    active = _active_scenarios(base_dir)
    sc_map = {d: (n, c, ls) for d, n, c, ls, _ in active}

    # failure と failure_rsvp の両方がないとグラフを描けない
    failure_dir     = next((d for d, n, *_ in active if n == "failure"), None)
    rsvp_dir        = next((d for d, n, *_ in active if n == "failure_rsvp"), None)
    normal_dir      = next((d for d, n, *_ in active if n == "normal"), None)

    if not failure_dir or not rsvp_dir:
        print("[skip] compare_rsvp_effect: failure / failure_rsvp のどちらかデータなし")
        return

    fig, axes = plt.subplots(3, 1, figsize=(11, 11), sharex=True)
    fig.suptitle(
        "RSVP-TE 効果  — failure vs failure_rsvp スループット比較",
        fontsize=14, fontweight="bold",
    )

    for ax, (pri_label, pri_color, col, tx, _) in zip(axes, PRIORITIES):
        def _load(dirname):
            csv = base_dir / dirname / "throughput.csv"
            return load_csv_throughput(csv, col) if csv.exists() else ([], [])

        t_fail, mb_fail = _load(failure_dir)
        t_rsvp, mb_rsvp = _load(rsvp_dir)

        # normal をグレー参照ラインとして描画
        if normal_dir:
            t_norm, mb_norm = _load(normal_dir)
            if t_norm:
                ax.plot(t_norm, mb_norm, color="gray", linestyle="--",
                        linewidth=1.2, alpha=0.5, label="normal (参照)", zorder=1)

        # failure（赤）と failure_rsvp（青）を描画
        if t_fail:
            ax.plot(t_fail, mb_fail, color="#d62728", linestyle="--",
                    linewidth=1.8, label="failure", zorder=3)
        if t_rsvp:
            ax.plot(t_rsvp, mb_rsvp, color="#1f77b4", linestyle="-",
                    linewidth=2.0, label="failure_rsvp", zorder=4)

        # 障害区間で failure_rsvp が failure より上回る部分を塗りつぶし（RSVP回復効果）
        if t_fail and t_rsvp:
            # 共通時刻グリッドに補間
            t_common = sorted(set(t_fail) | set(t_rsvp))
            t_common = [t for t in t_common if FAILURE_START <= t <= FAILURE_END]
            if t_common:
                mb_f_interp = np.interp(t_common, t_fail, mb_fail)
                mb_r_interp = np.interp(t_common, t_rsvp, mb_rsvp)
                ax.fill_between(
                    t_common,
                    mb_f_interp, mb_r_interp,
                    where=(mb_r_interp > mb_f_interp),
                    color="#1f77b4", alpha=0.18,
                    label="RSVP回復効果", zorder=2,
                )
                # 障害区間の中央に回復量テキストを表示
                mid = (FAILURE_START + FAILURE_END) / 2
                t_mid_idx = int(len(t_common) // 2)
                recovered = float(np.mean(mb_r_interp - mb_f_interp))
                if recovered > 0.5:
                    ax.annotate(
                        f"+{recovered:.0f} Mbit/s\n回復",
                        xy=(mid, (mb_r_interp[t_mid_idx] + mb_f_interp[t_mid_idx]) / 2),
                        xytext=(mid - 6, ax.get_ylim()[1] * 0.5),
                        fontsize=9, color="#1f77b4", fontweight="bold",
                        arrowprops=dict(arrowstyle="->", color="#1f77b4", lw=1.2),
                    )

        # 障害区間のシェーディングと垂直線
        ax.axvspan(FAILURE_START, FAILURE_END, alpha=0.06, color="red", zorder=0)
        ax.axvline(FAILURE_START, color="#d62728",   linestyle="--", lw=1.1, alpha=0.7)
        ax.axvline(FAILURE_END,   color="#1f77b4", linestyle="--", lw=1.1, alpha=0.7)

        ax.set_xlim(0, THR_X_MAX)
        ax.set_ylim(bottom=0)
        ax.set_title(f"● {pri_label}", color=pri_color, fontweight="bold", fontsize=12)
        ax.set_ylabel("Throughput (Mbit/s)")
        ax.legend(loc="lower right", fontsize=9)
        ax.grid(True, axis="y")

    axes[0].text(FAILURE_START + 0.3, axes[0].get_ylim()[1] * 0.96,
                 "障害開始", color="#d62728", fontsize=8, va="top")
    axes[0].text(FAILURE_END + 0.3, axes[0].get_ylim()[1] * 0.96,
                 "障害回復", color="#1f77b4", fontsize=8, va="top")
    axes[-1].set_xlabel("Time (s)")
    fig.tight_layout()
    out = base_dir / "compare_rsvp_effect.png"
    _save(fig, out)
    plt.close(fig)


# ═══════════════════════════════════════════════════════════════════════
# FRR シナリオ比較 (results/frr/ を base_dir として実行)
# ═══════════════════════════════════════════════════════════════════════

def run_frr_compare(frr_base: Path):
    """FRR_SCENARIOS を使い frr_base/ 以下のシナリオと比較グラフを生成する。
    SCENARIOS / FIGURES_DIR を一時的に上書きして既存の比較関数を再利用する。"""
    global SCENARIOS, FIGURES_DIR
    orig_scenarios = list(SCENARIOS)
    orig_figures   = FIGURES_DIR

    SCENARIOS[:]  = FRR_SCENARIOS
    FIGURES_DIR    = orig_figures / "frr"

    print("=== FRR シナリオ別グラフ生成 ===")
    for dirname, *_ in FRR_SCENARIOS:
        dirpath = frr_base / dirname
        if not dirpath.exists():
            print(f"  [skip] {dirname}: ディレクトリなし")
            continue
        if not has_data(dirpath):
            print(f"  [skip] {dirname}: データなし")
            continue
        print(f"\n--- {dirname} ---")
        main(dirpath)

    print("\n=== FRR 比較グラフ生成 ===")
    compare_throughput_priority(frr_base)
    compare_delay_priority(frr_base)
    compare_scenarios(frr_base)
    compare_delay(frr_base)
    compare_packet_loss(frr_base)

    SCENARIOS[:] = orig_scenarios
    FIGURES_DIR   = orig_figures

    print(f"\n=== FRR 完了  出力先: {frr_base} ===")


# ═══════════════════════════════════════════════════════════════════════
# エントリポイント
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    _positional = [a for a in sys.argv[1:] if not a.startswith("--")]
    _flags      = [a for a in sys.argv[1:] if a.startswith("--")]

    if "--show-loss" in _flags:
        SHOW_LOSS = True  # noqa: F811

    base = Path(__file__).resolve().parent

    if _positional:
        outdir = Path(_positional[0])
        if not outdir.is_absolute():
            outdir = base / outdir

        # ディレクトリが FRR base dir か判定 (throughput.csv がなく FRR サブディレクトリあり)
        frr_available = [d for d, *_ in FRR_SCENARIOS if (outdir / d).exists()]
        if outdir.is_dir() and frr_available and not (outdir / "throughput.csv").exists():
            run_frr_compare(outdir)
        else:
            print(f"\n=== {outdir.name} ===")
            main(outdir)
    else:
        # System A 全シナリオ自動生成
        print("=== シナリオ別グラフ生成 ===")
        for dirname, sc_name, *_ in SCENARIOS:
            dirpath = base / dirname
            if not dirpath.exists():
                print(f"  [skip] {dirname}: ディレクトリなし")
                continue
            if not has_data(dirpath):
                print(f"  [skip] {dirname}: データなし")
                continue
            print(f"\n--- {sc_name} ({dirname}) ---")
            main(dirpath)

        print("\n=== 比較グラフ生成 ===")
        compare_throughput_priority(base)
        compare_delay_priority(base)
        compare_scenarios(base)
        compare_delay(base)
        compare_packet_loss(base)
        compare_rsvp_effect(base)

        print(f"\n=== 完了  出力先: {base} ===")
