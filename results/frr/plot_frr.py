"""
plot_frr.py — FRR OSPF-SR + DiffServ-TE 比較グラフ生成 (査読品質)
"""
import argparse
import re
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import matplotlib.font_manager as fm
import numpy as np

_parser = argparse.ArgumentParser(description="FRR OSPF-SR + DiffServ-TE 比較グラフ生成")
_parser.add_argument("--base",    type=str,   default=None,
                     help="タグ名または絶対パス (省略時: 最新データを自動検出)")
_parser.add_argument("--cr-mbps", type=float, default=None,
                     help="CRリンク帯域 Mbps (省略時: lab_config.sh を自動参照)")
_parser.add_argument("--list",    action="store_true",
                     help="利用可能なタグ一覧を表示して終了")
_args = _parser.parse_args()

# ── フォント ──────────────────────────────────────────────────────────
for _f in ["Noto Sans CJK JP", "TakaoPGothic", "IPAPGothic", "VL PGothic"]:
    if any(_f.lower() in p.name.lower() for p in fm.fontManager.ttflist):
        matplotlib.rcParams["font.family"] = _f
        break

matplotlib.rcParams.update({
    "figure.facecolor":    "white",
    "axes.facecolor":      "white",
    "axes.spines.top":     False,
    "axes.spines.right":   False,
    "axes.linewidth":      0.8,
    "axes.labelsize":      9,
    "axes.titlesize":      9,
    "axes.titlepad":       4,
    "axes.labelpad":       3,
    "xtick.labelsize":     8,
    "ytick.labelsize":     8,
    "xtick.direction":     "out",
    "ytick.direction":     "out",
    "xtick.major.size":    3,
    "ytick.major.size":    3,
    "xtick.major.width":   0.8,
    "ytick.major.width":   0.8,
    "legend.fontsize":     8,
    "legend.framealpha":   0.9,
    "legend.edgecolor":    "0.8",
    "legend.borderpad":    0.4,
    "legend.labelspacing": 0.3,
    "legend.handlelength": 2.5,
    "lines.linewidth":     1.5,
    "patch.linewidth":     0.5,
    "grid.alpha":          0.3,
    "grid.linewidth":      0.5,
    "grid.linestyle":      ":",
    "savefig.dpi":         300,
    "savefig.bbox":        "tight",
    "savefig.pad_inches":  0.05,
})

_SCRIPT_DIR = Path(__file__).resolve().parent

def _parse_bw(s: str) -> float:
    """'25G'→25000, '30M'→30, '100K'→0.1"""
    s = s.strip().upper()
    if s.endswith("G"): return float(s[:-1]) * 1000
    if s.endswith("M"): return float(s[:-1])
    if s.endswith("K"): return float(s[:-1]) / 1000
    return float(s)

def _lab_cr_mbps() -> float | None:
    # TX レート (_lab_tx_mbps) と同じ優先順で参照し、TX/CR の設定ファイル不整合を防ぐ
    for cfg_name in ("lab_config_veth.sh", "lab_config_physical.sh", "lab_config.sh"):
        lab = _SCRIPT_DIR.parent.parent / "scripts" / cfg_name
        if not lab.exists():
            continue
        for ln in lab.read_text().splitlines():
            m = re.match(r'CR1_BW="\$\{CR1_BW:-([^}]+)\}"', ln)
            if m:
                return _parse_bw(m.group(1))
    return None

def _lab_tx_mbps() -> tuple[float, float, float] | None:
    """TX1/TX2/TX3 レートを Mbps で返す。ストリーム数(4)を乗じた総送信量。"""
    for cfg_name in ("lab_config_veth.sh", "lab_config_physical.sh", "lab_config.sh"):
        lab = _SCRIPT_DIR.parent.parent / "scripts" / cfg_name
        if not lab.exists():
            continue
        txt = lab.read_text()
        rates = {}
        for key in ("TX1_RATE", "TX2_RATE", "TX3_RATE"):
            m = re.search(rf'{key}="\$\{{{key}:-([^}}]+)\}}"', txt)
            if m:
                rates[key] = _parse_bw(m.group(1))
        if len(rates) == 3:
            # veth は 4ストリーム、physical は 1ストリーム
            streams = 1 if "physical" in cfg_name else 4
            return (rates["TX1_RATE"] * streams,
                    rates["TX2_RATE"] * streams,
                    rates["TX3_RATE"] * streams)
    return None

def _has_scenario_data(d: Path) -> bool:
    return any(
        (sub / f).exists()
        for sub in (d.iterdir() if d.is_dir() else [])
        if sub.is_dir()
        for f in ("throughput.csv", "htb_class_stats.csv")
    )

def _list_tags() -> list[str]:
    return sorted(
        (d.name for d in _SCRIPT_DIR.iterdir()
         if d.is_dir() and d.name not in ("__pycache__", "figures")
         and _has_scenario_data(d)),
        reverse=True,
    )

def _resolve_base(tag: str | None) -> Path:
    if tag:
        p = Path(tag)
        return p if p.is_absolute() else _SCRIPT_DIR / tag
    candidates = sorted(
        (d for d in _SCRIPT_DIR.iterdir()
         if d.is_dir() and d.name not in ("__pycache__", "figures")
         and _has_scenario_data(d)),
        key=lambda d: d.stat().st_mtime, reverse=True,
    )
    return candidates[0] if candidates else _SCRIPT_DIR

BASE         = _resolve_base(_args.base)
FIGURES_DIR  = BASE / "figures"
FAILURE_START, FAILURE_END = 20, 40
PLOT_END     = 60
DATA_END     = 59.5   # 計測終端の端数サンプル（部分区間）を除外

_WRR          = (4, 2, 1)
_CR_LINK_MBPS = _args.cr_mbps if _args.cr_mbps is not None else (_lab_cr_mbps() or 25000.0)
_tx_totals    = _lab_tx_mbps()
# SP+WRR 理論値:
#   AF41 = min(送信量, リンク容量)          — prio0(SP) が借用プールを最優先で獲得
#   残余 = リンク容量 - AF41
#   AF42 = min(送信量, 残余×2/3), AF43 = min(送信量, 残余×1/3)
#   (HTB保証rateは全クラス1/10縮小かつ重み比と同じ2:1のため、残余のWRR比分配と一致)
if _tx_totals:
    _af41_t   = min(_tx_totals[0], _CR_LINK_MBPS)
    _residual = max(_CR_LINK_MBPS - _af41_t, 0.0)
    _w2, _w3  = _WRR[1], _WRR[2]
    THEORY_TARGETS = [
        _af41_t,
        min(_tx_totals[1], _residual * _w2 / (_w2 + _w3)),
        min(_tx_totals[2], _residual * _w3 / (_w2 + _w3)),
    ]
else:
    THEORY_TARGETS = [_CR_LINK_MBPS * w / sum(_WRR) for w in _WRR]

THRU_UNIT  = "Gbps" if _CR_LINK_MBPS >= 1000 else "Mbps"
THRU_SCALE = 1e-3   if _CR_LINK_MBPS >= 1000 else 1.0

# トラフィッククラス — Wong (2011) colorblind-safe
PRIORITIES = [
    ("AF41（高優先）", "#0072B2", 1, "Tx1"),
    ("AF42（中優先）", "#E69F00", 2, "Tx2"),
    ("AF43（低優先）", "#009E73", 3, "Tx3"),
]
CLS_LABELS = ["AF41\n（高優先）", "AF42\n（中優先）", "AF43\n（低優先）"]

_OWD_NAMES   = {1: "owd_af41.log", 2: "owd_af42.log", 3: "owd_af43.log"}
_IPERF_NAMES = {1: "iperf3_af41.log", 2: "iperf3_af42.log", 3: "iperf3_af43.log"}
_IPERF_LOSS_RE = re.compile(r'\[SUM\].*\s+(\d+)/(\d+)\s+\([0-9.]+%\)\s+receiver')

# シナリオスタイル — 色 + 線種の組み合わせでグレースケール印刷でも判別可能
_SC_STYLES = {
    "normal":  {"color": "#4CAE4C", "ls": "-",  "lw": 1.6, "label": "正常時"},
    "failure": {"color": "#DC4748", "ls": "--", "lw": 1.6, "label": "障害（迂回なし）"},
    "reroute": {"color": "#418BBF", "ls": "-.", "lw": 1.6, "label": "障害（自動迂回）"},
}

# ── シナリオ検出 ──────────────────────────────────────────────────────
def _scenario_style(name: str) -> dict:
    if "normal" in name and "failure" not in name:
        return _SC_STYLES["normal"]
    if "reroute" in name:
        return _SC_STYLES["reroute"]
    if "failure" in name:
        return _SC_STYLES["failure"]
    return {"color": "gray", "ls": "-", "lw": 1.4, "label": name}

def _scenario_order(name: str) -> int:
    """表示順: normal → failure → failure_reroute"""
    if "normal" in name and "failure" not in name:
        return 0
    if "reroute" in name:
        return 2
    if "failure" in name:
        return 1
    return 3

def _discover_scenarios():
    dirs = sorted((d for d in BASE.iterdir() if d.is_dir() and d.name != "__pycache__"),
                  key=lambda d: (_scenario_order(d.name), d.name))
    result = []
    for d in dirs:
        st = _scenario_style(d.name)
        result.append((d.name, st["label"], st["color"], st["ls"],
                       "failure" in d.name, st["lw"]))
    return result

def has_data(dirpath: Path) -> bool:
    def _nonzero(p: Path) -> bool:
        if not p.exists():
            return False
        return sum(
            1 for ln in p.read_text(errors="ignore").splitlines()
            if not ln.startswith("time") and ln.strip()
            and not all(v.strip() == "0" for v in ln.split(",")[1:])
        ) > 5
    if _nonzero(dirpath / "htb_class_stats.csv"):
        return True
    if _nonzero(dirpath / "throughput.csv"):
        return True
    chk = re.compile(r"time=[0-9.]+\s*ms")
    for _, _, _, tx in PRIORITIES:
        p = dirpath / f"{tx}_ping.log"
        if p.exists() and chk.search(p.read_text(errors="ignore")):
            return True
    return False

def active_scenarios():
    return [(d, n, c, ls, f, lw)
            for d, n, c, ls, f, lw in _discover_scenarios()
            if has_data(BASE / d)]

# ── 保存 (PNG + PDF) ──────────────────────────────────────────────────
def _save(fig, stem: str):
    FIGURES_DIR.mkdir(exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(FIGURES_DIR / f"{stem}.{ext}")
    fig.savefig(BASE / f"{stem}.png")
    print(f"[*] {stem}.png / .pdf")

# ── データ読み込み ────────────────────────────────────────────────────
_RX_KEYS = ["rx1_bytes_per_sec", "rx2_bytes_per_sec", "rx3_bytes_per_sec"]

def _parse_iperf3_loss(log_path: Path) -> float | None:
    """iperf3 ログ receiver 行から合計損失率 (%) を返す。なければ None。"""
    if not log_path.exists():
        return None
    for line in reversed(log_path.read_text(errors="ignore").splitlines()):
        m = _IPERF_LOSS_RE.search(line)
        if m:
            lost, total = int(m.group(1)), int(m.group(2))
            return lost / total * 100 if total > 0 else 0.0
    return None

def _compute_baselines(active: list) -> list:
    import csv as _csv
    for d, *_ in active:
        if "normal" in d and "failure" not in d:
            p = BASE / d / "throughput.csv"
            if not p.exists():
                break
            rows = [r for r in _csv.DictReader(p.read_text().splitlines())
                    if float(r.get("time", -1)) < FAILURE_START]
            if len(rows) >= 5:
                return [sum(float(r[k]) for r in rows) / len(rows) * 8 / 1e6
                        for k in _RX_KEYS]
            break
    return list(THEORY_TARGETS)

def _load_throughput(csv_path, col):
    rows = []
    for ln in Path(csv_path).read_text().splitlines():
        if ln.startswith("time") or not ln.strip():
            continue
        parts = ln.split(",")
        if len(parts) <= col:
            continue
        try:
            t = float(parts[0])
            if t > DATA_END:
                continue
            rows.append((t, int(parts[col]) * 8 / 1e6))
        except ValueError:
            continue
    rows.sort(key=lambda x: x[0])
    return ([r[0] for r in rows], [r[1] for r in rows]) if rows else ([], [])

_OWD_RE  = re.compile(r"\[([0-9]+\.[0-9]+)\].*seq=\d+.*owd=([0-9.-]+) ms")
_PING_RE = re.compile(r"^\[([0-9]+\.[0-9]+)\].*time=([0-9.]+)\s*ms")

def _insert_gap_nans(ts, vals, gap_thr: float = 2.0):
    """連続するデータ点の間隔が gap_thr 秒を超えた箇所に NaN を挿入し
    matplotlib がギャップを線で繋がないようにする。"""
    if len(ts) < 2:
        return ts, vals
    new_ts, new_vals = [ts[0]], [vals[0]]
    for i in range(1, len(ts)):
        if ts[i] - ts[i - 1] > gap_thr:
            new_ts.append(float("nan"))
            new_vals.append(float("nan"))
        new_ts.append(ts[i])
        new_vals.append(vals[i])
    return new_ts, new_vals

def _load_owd(path: Path):
    ts, vals, t0 = [], [], None
    for ln in path.read_text(errors="ignore").splitlines():
        m = _OWD_RE.search(ln)
        if m:
            t = float(m.group(1))
            if t0 is None: t0 = t
            if t - t0 > DATA_END:
                continue
            ts.append(t - t0); vals.append(float(m.group(2)))
    return _insert_gap_nans(ts, vals)

def _load_ping_rtt(path: Path):
    ts, vals, t0 = [], [], None
    for ln in path.read_text(errors="ignore").splitlines():
        m = _PING_RE.match(ln.strip())
        if m:
            t = float(m.group(1))
            if t0 is None: t0 = t
            if t - t0 > DATA_END:
                continue
            ts.append(t - t0); vals.append(float(m.group(2)))
    return _insert_gap_nans(ts, vals)

def _find_owd(dirpath: Path, col: int):
    for name in (_OWD_NAMES.get(col, ""), f"Tx{col}_owd.log"):
        if name and (dirpath / name).exists():
            return dirpath / name
    return None

def _load_per_class_throughput(dirpath: Path, col: int):
    htb1, htb2 = dirpath / "htb_class_stats.csv", dirpath / "htb_class_stats_cr2.csv"
    t1, mb1 = (_load_throughput(htb1, col) if htb1.exists() else ([], []))
    t2, mb2 = (_load_throughput(htb2, col) if htb2.exists() else ([], []))
    if t1 or t2:
        d1, d2 = dict(zip(t1, mb1)), dict(zip(t2, mb2))
        all_t = sorted(set(t1) | set(t2))
        if all_t:
            return all_t, [d1.get(t, 0.0) + d2.get(t, 0.0) for t in all_t]
    return _load_throughput(dirpath / "throughput.csv", col)

# ── failure ゾーン描画 ─────────────────────────────────────────────────
def _mark_failure(ax, annotate: bool = False):
    ax.axvspan(FAILURE_START, FAILURE_END, alpha=0.06, color="#C0392B", zorder=0)
    ax.axvline(FAILURE_START, color="#C0392B", ls=":", lw=0.9, zorder=1)
    ax.axvline(FAILURE_END,   color="#2471A3", ls=":", lw=0.9, zorder=1)
    ax.grid(True, axis="y", zorder=0)
    if annotate:
        mid = (FAILURE_START + FAILURE_END) / 2
        ax.text(mid, 1.01, "障害区間", transform=ax.get_xaxis_transform(),
                ha="center", va="bottom", fontsize=7, color="#888888")

# ── (a)(b)(c) パネルラベル ────────────────────────────────────────────
def _panel_label(ax, idx: int):
    ax.text(-0.10, 1.05, f"({chr(97 + idx)})",
            transform=ax.transAxes, fontsize=9, fontweight="bold", va="top")

# ── compare_throughput ────────────────────────────────────────────────
def compare_throughput(active):
    fig, axes = plt.subplots(3, 1, figsize=(7, 7), sharex=True, layout="constrained")
    fig.suptitle("スループット比較", fontsize=10, fontweight="bold")

    for i, (ax, (pri_label, pri_color, col, _), wrr_tgt) in \
            enumerate(zip(axes, PRIORITIES, THEORY_TARGETS)):
        for d, n, c, ls, _, lw in active:
            t, mb = _load_per_class_throughput(BASE / d, col)
            if t:
                ax.plot(t, [v * THRU_SCALE for v in mb],
                        label=n, color=c, linestyle=ls, linewidth=lw)
        ax.axhline(wrr_tgt * THRU_SCALE, color=pri_color, ls=":", lw=1.0, alpha=0.7,
                   label=f"理論値 ({wrr_tgt * THRU_SCALE:.2f} {THRU_UNIT})")
        ax.set_xlim(0, PLOT_END)
        ax.set_ylim(bottom=0)
        ax.set_ylabel(f"スループット ({THRU_UNIT})")
        ax.set_title(pri_label, color=pri_color, fontweight="bold", loc="left", pad=2)
        ax.legend(loc="lower right")
        _mark_failure(ax, annotate=(i == 0))
        _panel_label(ax, i)

    axes[-1].set_xlabel("経過時間 (s)")
    _save(fig, "compare_throughput")
    plt.close(fig)

# ── compare_rtt ────────────────────────────────────────────────────────
def compare_rtt(active):
    fig, axes = plt.subplots(3, 1, figsize=(7, 7), sharex=True, layout="constrained")
    fig.suptitle("片方向遅延 (OWD) 比較", fontsize=10, fontweight="bold")

    for i, (ax, (pri_label, pri_color, col, tx)) in enumerate(zip(axes, PRIORITIES)):
        all_vals = []
        peak = None   # (t, val, color) — パネル内グローバル最大のみ注記
        for d, n, c, ls, _, lw in active:
            owd_p  = _find_owd(BASE / d, col)
            ping_p = BASE / d / f"{tx}_ping.log"
            if owd_p:
                t, vals = _load_owd(owd_p)
            elif ping_p.exists():
                t, vals = _load_ping_rtt(ping_p)
            else:
                continue
            if t:
                ax.plot(t, vals, label=n, color=c, linestyle=ls, linewidth=lw, alpha=0.9)
                all_vals.extend(vals)
                peak_idx = int(np.nanargmax(vals))
                peak_val = float(vals[peak_idx])
                if peak is None or peak_val > peak[1]:
                    peak = (float(t[peak_idx]), peak_val, c)
        if peak is not None:
            right_edge = peak[0] > PLOT_END * 0.8
            ax.annotate(f"最大 {peak[1]:.1f} ms",
                        xy=(peak[0], peak[1]),
                        xytext=(-4 if right_edge else 4, 4),
                        textcoords="offset points",
                        ha="right" if right_edge else "left",
                        fontsize=6.5, color=peak[2],
                        arrowprops=dict(arrowstyle="-", color=peak[2], lw=0.5))
        if all_vals:
            global_max = float(np.nanmax(all_vals))
            ax.set_ylim(bottom=0, top=global_max * 1.20)
        ax.set_xlim(0, PLOT_END)
        ax.set_ylabel("片方向遅延 (ms)")
        ax.set_title(pri_label, color=pri_color, fontweight="bold", loc="left", pad=2)
        ax.legend(loc="upper right")
        _mark_failure(ax, annotate=(i == 0))
        _panel_label(ax, i)

    axes[-1].set_xlabel("経過時間 (s)")
    _save(fig, "compare_rtt")
    plt.close(fig)

# ── compare_packetloss ────────────────────────────────────────────────
def compare_packetloss(active):
    """iperf3 の UDP Lost/Total から実測パケットロス率を棒グラフ化。"""
    loss_data = {}
    for d, n, *_ in active:
        losses = []
        for col in (1, 2, 3):
            v = _parse_iperf3_loss(BASE / d / _IPERF_NAMES[col])
            losses.append(v if v is not None else float("nan"))
        loss_data[n] = losses

    n_sc  = len(active)
    x     = np.arange(3)
    width = 0.6 / max(n_sc, 1)

    fig, ax = plt.subplots(figsize=(6, 4), layout="constrained")
    fig.suptitle("UDP パケットロス率  (iperf3 実測, 60 s 平均)",
                 fontsize=10, fontweight="bold")

    for i, (_, n, c, *_) in enumerate(active):
        vals   = loss_data.get(n, [float("nan")] * 3)
        offset = (i - (n_sc - 1) / 2) * width
        bars   = ax.bar(x + offset, vals, width, label=n,
                        color=c, alpha=0.85,
                        edgecolor="white", linewidth=0.5)
        for bar, v in zip(bars, vals):
            if not np.isnan(v):
                ax.text(bar.get_x() + bar.get_width() / 2, v + 0.8,
                        f"{v:.1f}%", ha="center", va="bottom",
                        fontsize=7, fontweight="bold", color=c)

    ax.set_xticks(x)
    ax.set_xticklabels(CLS_LABELS)
    ax.set_ylabel("パケットロス率 (%)")
    ax.set_ylim(0, 110)
    ax.yaxis.set_major_locator(ticker.MultipleLocator(20))
    ax.grid(axis="y")
    ax.legend(loc="upper left")

    _save(fig, "compare_packetloss")
    plt.close(fig)

# ── compare_loss_timeseries ───────────────────────────────────────────
def compare_loss_timeseries(active):
    """iperf3 -i 1 サーバ側 [SUM] 行から毎秒 E2E パケット損失率を表示。
    lost/total を直接使用するため送信レート仮定不要。"""

    # iperf3 server-output [SUM] 毎秒行: lost/total → 損失率(%)
    _SUM_RE = re.compile(
        r'\[SUM\]\s+(\d+\.\d+)-(\d+\.\d+)\s+sec'   # 区間
        r'.*?(\d+)/(\d+)\s+\([0-9.]+%\)'            # lost/total
    )

    def _load_e2e_loss(dirpath, suffix):
        p = dirpath / f"iperf3_{suffix}.log"
        if not p.exists():
            return [], []
        text = p.read_text()
        idx = text.find("Server output:")
        if idx < 0:
            return [], []
        ts, losses = [], []
        for m in _SUM_RE.finditer(text, idx):
            t_start, t_end = float(m.group(1)), float(m.group(2))
            if t_end - t_start > 1.5:   # 最終サマリ行はスキップ
                continue
            if t_start >= DATA_END:
                continue
            lost  = int(m.group(3))
            total = int(m.group(4))
            # total=0 は当該1秒間に1個も受信できなかった区間（完全断）= 100% 損失
            loss_pct = 100.0 if total == 0 else lost / total * 100.0
            ts.append(t_start + 0.5)    # 区間中央を時刻に
            losses.append(loss_pct)
        return ts, losses

    _SUFFIXES = ["af41", "af42", "af43"]

    # 既存データが -i 0 形式（毎秒行なし）かを確認して fallback メッセージ用に使う
    def _has_interval_data(dirpath, suffix):
        ts, _ = _load_e2e_loss(dirpath, suffix)
        return len(ts) > 0

    fig, axes = plt.subplots(3, 1, figsize=(7, 7), sharex=True, layout="constrained")
    fig.suptitle("パケット損失率  (E2E, iperf3 毎秒計測)",
                 fontsize=10, fontweight="bold")

    for i, (ax, (pri_label, pri_color, _, _)) in enumerate(zip(axes, PRIORITIES)):
        suf = _SUFFIXES[i]
        any_data = False
        for d, n, c, ls, _, lw in active:
            ts, vals = _load_e2e_loss(BASE / d, suf)
            if not ts:
                continue
            ax.plot(ts, vals, color=c, ls=ls, linewidth=lw, label=n, alpha=0.9)
            any_data = True

        if not any_data:
            ax.text(0.5, 0.5,
                    "データなし\n（frr_measure.sh -i 1 で再計測が必要）",
                    transform=ax.transAxes, ha="center", va="center",
                    fontsize=9, color="gray")

        _mark_failure(ax, annotate=(i == 0))
        ax.set_ylabel("損失率 (%)")
        ax.set_ylim(-2, 105)
        ax.yaxis.set_major_locator(ticker.MultipleLocator(25))
        ax.set_title(pri_label, color=pri_color, fontweight="bold", loc="left", pad=2)
        ax.legend(loc="upper right")
        _panel_label(ax, i)

    axes[-1].set_xlabel("経過時間 (s)")
    axes[-1].set_xlim(0, PLOT_END)
    _save(fig, "compare_loss_timeseries")
    plt.close(fig)

# ── compare_drop_location ─────────────────────────────────────────────
def compare_drop_location(active):
    """インタフェース別2パネル × シナリオ3本線。
    leri-cr1 パネル: 輻輳ドロップが常時発生 / 障害時は一時ゼロ
    leri-cr2 パネル: 平常時ゼロ / failure_reroute 障害中のみ出現 → 迂回の証拠"""
    import csv as _csv

    def _load_iface_drops(dirpath, iface):
        p = dirpath / "tc_drops.csv"
        if not p.exists():
            return [], []
        td = {}
        for r in _csv.DictReader(p.read_text().splitlines()):
            if r.get("iface") != iface:
                continue
            try:
                t = float(r["time"])
                if t > DATA_END:
                    continue
                td[t] = td.get(t, 0.0) + float(r["drops_per_sec"])
            except (ValueError, KeyError):
                pass
        ts = sorted(td)
        return ts, [td[t] for t in ts]

    def _smooth(ts, vs, win=5):
        """因果移動平均（過去 win 点のみ）。未来値を使わないため障害境界で前方滲みが生じない。"""
        if len(vs) < win:
            return ts, vs
        arr = np.array(vs, dtype=float)
        # 先頭のみ pad して causal convolution
        padded = np.pad(arr, (win - 1, 0), mode="edge")
        smoothed = np.convolve(padded, np.ones(win) / win, mode="valid")
        return ts, smoothed.tolist()

    IFACES = [
        ("leri-cr1", "HTB ドロップ  —  leri-cr1 (→ CR1)"),
        ("leri-cr2", "HTB ドロップ  —  leri-cr2 (→ CR2)"),
    ]

    # Y軸スケールを全シナリオ・全インタフェースの最大値から決定
    global_max = 0.0
    for d, *_ in active:
        for iface, _ in IFACES:
            _, vs = _load_iface_drops(BASE / d, iface)
            if vs:
                global_max = max(global_max, max(vs))
    if global_max >= 1e6:
        scale, unit = 1e-6, "Mpkt/s"
    elif global_max >= 1e3:
        scale, unit = 1e-3, "kpkt/s"
    else:
        scale, unit = 1.0, "pkt/s"

    any_fail = any(f for *_, f, _ in active)

    fig, axes = plt.subplots(2, 1, figsize=(7, 5.5),
                             sharex=True, sharey=True, layout="constrained")
    fig.suptitle("パケットドロップ発生箇所  (LER_Ingress 出口)",
                 fontsize=10, fontweight="bold")

    for pi, (ax, (iface, title)) in enumerate(zip(axes, IFACES)):
        plotted = False
        for d, n, c, ls, is_fail, lw in active:
            ts, vs = _load_iface_drops(BASE / d, iface)
            if not ts:
                continue
            ts_s, vs_s = _smooth(ts, vs)
            ax.plot(ts_s, [v * scale for v in vs_s],
                    color=c, ls=ls, linewidth=lw, label=n, alpha=0.9)
            plotted = True

        if not plotted:
            ax.text(0.5, 0.5, "データなし（再計測で収集）",
                    transform=ax.transAxes, ha="center", va="center",
                    fontsize=9, color="gray")

        if any_fail:
            _mark_failure(ax, annotate=(pi == 0))
        else:
            ax.grid(True, axis="y")

        ax.set_title(title, fontweight="bold", loc="left", pad=2)
        ax.set_ylabel(f"ドロップ数 ({unit})")
        ax.set_xlim(0, PLOT_END)
        ax.set_ylim(bottom=0)
        ax.legend(loc="lower right")
        _panel_label(ax, pi)

    axes[-1].set_xlabel("経過時間 (s)")
    fig.text(0.0, -0.015,
             "注: ドロップ数は tc (HTB) キューでの破棄カウンタ。GSO 集約された skb 単位のため、"
             "UDP データグラム数換算より小さい値となる。",
             ha="left", va="top", fontsize=6.5, color="#666666")
    _save(fig, "compare_drop_location")
    plt.close(fig)

# ── エントリポイント ──────────────────────────────────────────────────
if __name__ == "__main__":
    if _args.list:
        tags = _list_tags()
        if tags:
            print("利用可能なタグ:")
            for t in tags:
                print(f"  {t}")
        else:
            print("データなし")
        raise SystemExit(0)

    active = active_scenarios()
    if not active:
        print(f"[ERROR] データなし: {BASE}")
        tags = _list_tags()
        if tags:
            print("利用可能なタグ:")
            for t in tags:
                print(f"  python3 plot_frr.py --base {t}")
        raise SystemExit(1)

    print(f"結果ディレクトリ : {BASE.name}")
    print(f"CRリンク帯域     : {_CR_LINK_MBPS:.0f} Mbps")
    print(f"検出シナリオ     : {[n for _, n, *_ in active]}")
    print(f"理論値 (SP+WRR)  : AF41={THEORY_TARGETS[0]*THRU_SCALE:.1f} / "
          f"AF42={THEORY_TARGETS[1]*THRU_SCALE:.1f} / "
          f"AF43={THEORY_TARGETS[2]*THRU_SCALE:.1f} {THRU_UNIT}")
    print()

    compare_throughput(active)
    compare_rtt(active)
    compare_packetloss(active)
    compare_loss_timeseries(active)
    compare_drop_location(active)

    print(f"\n完了 → {FIGURES_DIR}")
