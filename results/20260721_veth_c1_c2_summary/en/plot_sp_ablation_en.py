"""
plot_sp_ablation_en.py — English figures for international-conference presentation.

Six-condition comparison of DiffServ-TE (HTB Strict Priority + WRR):
  environments  : veth (simulation) vs C2 (hardware testbed)
  SP mode       : enabled (SP+WRR) vs disabled (uniform priority = WRR only)
  scenarios     : normal / failure(no reroute) / failure(auto-reroute)

All loss/throughput/OWD values are parsed directly from the iperf3 / OWD logs
under <project>/results/frr, so re-running always reflects the latest data.

Presentation styling: clean sans-serif, larger fonts, 300 dpi, PDF+PNG.
"""
from pathlib import Path
import re
import math as _math
import matplotlib
import matplotlib.pyplot as plt
import numpy as np

# 出力はこのスクリプトと同じフォルダ(en/)。データは <project>/results/frr/。
OUT_DIR = Path(__file__).resolve().parent
_results = next(a for a in Path(__file__).resolve().parents if a.name == "results")
DATA_DIR = _results / "frr"

# ── Presentation-quality styling (clean sans-serif, larger fonts) ──────────
matplotlib.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica", "Liberation Sans"],
    "figure.facecolor": "white", "axes.facecolor": "white",
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.linewidth": 1.0,
    "axes.labelsize": 13, "axes.titlesize": 13,
    "xtick.labelsize": 12, "ytick.labelsize": 12,
    "legend.fontsize": 11, "legend.framealpha": 0.92, "legend.edgecolor": "0.7",
    "grid.alpha": 0.3, "grid.linewidth": 0.6, "grid.linestyle": ":",
    "lines.linewidth": 1.6,
    "savefig.dpi": 300, "savefig.bbox": "tight", "savefig.pad_inches": 0.06,
})

def headroom_linear(ax, frac=0.18, bottom=0.0):
    ymax = 0.0
    for ln in ax.get_lines():
        yd = [v for v in ln.get_ydata() if v is not None and not _math.isnan(v)]
        if yd:
            ymax = max(ymax, max(yd))
    if ymax > 0:
        ax.set_ylim(bottom, ymax * (1.0 + frac))

def headroom_log(ax, factor=2.2, bottom=None):
    ymax = 0.0
    for ln in ax.get_lines():
        yd = [v for v in ln.get_ydata() if v is not None and not _math.isnan(v) and v > 0]
        if yd:
            ymax = max(ymax, max(yd))
    if ymax > 0:
        ax.set_ylim(top=ymax * factor)
    if bottom is not None:
        ax.set_ylim(bottom=bottom)

# ── Data sources (label, folder, CR bandwidth Gbps) ────────────────────────
# All environments unified at CR=9G, TX=8G/class (veth re-measured at 9G).
# Figures use veth (simulation baseline) and C2 (hardware testbed, 3 independent
# physical paths). C1 (shared trunk) is nearly identical to C2 and kept only in
# the comparison table.
CONDITIONS = {
    "sp": [
        ("veth (sim.)\n(C=9 G)", "20260721_veth9G_sp_enabled", 9),
        ("C2 (testbed)\n(C=9 G)", "20260721_c2_sp_enabled", 9),
    ],
    "uniform": [
        ("veth (sim.)\n(C=9 G)", "20260721_veth9G_sp_uniform", 9),
        ("C2 (testbed)\n(C=9 G)", "20260721_c2_sp_uniform", 9),
    ],
}

_SUM_RE = re.compile(r"([\d.]+)\s*([KMG]?)bits/sec.*?\(([\d.]+)%\)\s+receiver")

def parse_iperf(folder, cls):
    log = DATA_DIR / folder / "frr_normal" / f"iperf3_{cls}.log"
    for line in log.read_text().splitlines():
        if "SUM" in line and "receiver" in line:
            m = _SUM_RE.search(line)
            if m:
                val, unit, loss = float(m.group(1)), m.group(2), float(m.group(3))
                gbps = {"G": val, "M": val/1e3, "K": val/1e6, "": val/1e9}[unit]
                return gbps, loss
    raise RuntimeError(f"parse failed: {log}")

_OWD_TS_RE = re.compile(r"\[([\d.]+)\]\s+seq=\d+\s+owd=([\d.]+)")

def parse_owd_series(folder, cls, scenario="frr_normal"):
    log = DATA_DIR / folder / scenario / f"owd_{cls}.log"
    ts, ms = [], []
    for line in log.read_text().splitlines():
        m = _OWD_TS_RE.search(line)
        if m:
            ts.append(float(m.group(1)))
            ms.append(float(m.group(2)))
    if not ts:
        raise RuntimeError(f"OWD parse failed: {log}")
    t0 = ts[0]
    return [t - t0 for t in ts], ms

def parse_owd_binned(folder, cls, scenario="frr_normal", span=60):
    """Per-second median OWD; seconds with no received packets -> NaN (line gap).
    Outage periods (all packets dropped) appear as breaks, avoiding false lines."""
    t, ms = parse_owd_series(folder, cls, scenario)
    buckets = {}
    for ti, mi in zip(t, ms):
        buckets.setdefault(int(ti), []).append(mi)
    xs = list(range(span))
    ys = []
    for s in xs:
        v = buckets.get(s)
        if v:
            v.sort()
            ys.append(v[len(v)//2])
        else:
            ys.append(_math.nan)
    return xs, ys

def parse_throughput_series(folder, rx_idx, scenario="frr_normal"):
    csv = DATA_DIR / folder / scenario / "throughput.csv"
    t, gbps = [], []
    for line in csv.read_text().splitlines()[1:]:
        parts = line.split(",")
        if len(parts) >= 4:
            t.append(float(parts[0]))
            gbps.append(float(parts[rx_idx]) * 8 / 1e9)
    return t, gbps

# ── Collect scalar data ────────────────────────────────────────────────────
data = {}
for mode in ("sp", "uniform"):
    data[mode] = {c: [] for c in ("af41", "af42", "af43")}
    for label, folder, cr in CONDITIONS[mode]:
        for cls in ("af41", "af42", "af43"):
            gbps, loss = parse_iperf(folder, cls)
            data[mode][cls].append((label, gbps, loss))

labels = [c[0] for c in CONDITIONS["sp"]]
x = np.arange(len(labels))
w = 0.38
C_SP, C_UNIFORM = "#2c7fb8", "#d95f0e"

# ══ Main figure: AF41 loss rate (log-scale grouped bars) ════════════════════
fig, ax = plt.subplots(figsize=(6.0, 4.2))
sp_loss  = [max(v[2], 1e-4) for v in data["sp"]["af41"]]
uni_loss = [max(v[2], 1e-4) for v in data["uniform"]["af41"]]
b1 = ax.bar(x - w/2, sp_loss,  w, label="SP enabled (AF41 = Strict Priority)",
            color=C_SP, edgecolor="black", linewidth=0.5)
b2 = ax.bar(x + w/2, uni_loss, w, label="SP disabled (uniform priority = WRR only)",
            color=C_UNIFORM, edgecolor="black", linewidth=0.5)
ax.set_yscale("log")
ax.set_ylim(1e-3, 200)
ax.set_ylabel("AF41 (high-priority) packet loss rate [%]")
ax.set_xticks(x); ax.set_xticklabels(labels)
ax.set_title("AF41 Packet Loss: With vs Without Strict Priority (normal scenario)")
ax.grid(axis="y", which="both")
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=1,
          columnspacing=1.0, handlelength=1.6)
for bars, vals in ((b1, [v[2] for v in data["sp"]["af41"]]),
                   (b2, [v[2] for v in data["uniform"]["af41"]])):
    for rect, val in zip(bars, vals):
        txt = f"{val:.4f}%" if val < 1 else f"{val:.0f}%"
        ax.annotate(txt, (rect.get_x()+rect.get_width()/2, rect.get_height()),
                    ha="center", va="bottom", fontsize=10,
                    xytext=(0, 2), textcoords="offset points")
fig.tight_layout()
fig.savefig(OUT_DIR / "fig_af41_loss_ablation.png")
fig.savefig(OUT_DIR / "fig_af41_loss_ablation.pdf")
plt.close(fig)
print("[*] fig_af41_loss_ablation")

# ══ Per-class throughput bars (two panels: SP enabled / disabled) ═══════════
fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.2), sharey=True)
cls_names = ["AF41 (high)", "AF42 (med)", "AF43 (low)"]
cls_colors = ["#4CAE4C", "#f0ad4e", "#5bc0de"]
cw = 0.26
for ax, mode, title in ((axes[0], "sp", "SP enabled (Strict Priority + WRR)"),
                        (axes[1], "uniform", "SP disabled (WRR quantum ratio 4:2:1 only)")):
    for i, cls in enumerate(("af41", "af42", "af43")):
        vals = [v[1] for v in data[mode][cls]]
        ax.bar(x + (i-1)*cw, vals, cw, label=cls_names[i],
               color=cls_colors[i], edgecolor="black", linewidth=0.5)
        for xi, val in zip(x + (i-1)*cw, vals):
            ax.annotate(f"{val:.2f}", (xi, val), ha="center", va="bottom",
                        fontsize=9, xytext=(0, 1.5), textcoords="offset points")
    ax.set_xticks(x); ax.set_xticklabels(labels)
    ax.set_title(title); ax.grid(axis="y")
    ax.set_xlabel("Environment")
axes[0].set_ylabel("Received throughput [Gbps]")
_bar_ymax = max(v[1] for m in ("sp", "uniform") for c in ("af41", "af42", "af43")
                for v in data[m][c])
axes[0].set_ylim(0, _bar_ymax * 1.15)
axes[1].legend(loc="upper right", title="Traffic class")
fig.suptitle("Per-class Throughput: Bandwidth Allocation With vs Without SP", fontsize=14)
fig.tight_layout()
fig.savefig(OUT_DIR / "fig_class_throughput_ablation.png")
fig.savefig(OUT_DIR / "fig_class_throughput_ablation.pdf")
plt.close(fig)
print("[*] fig_class_throughput_ablation")

# ── Common definitions for time-series figures ─────────────────────────────
cls_keys = ("af41", "af42", "af43")
cls_labels = ["AF41 (high-priority)", "AF42 (medium-priority)", "AF43 (low-priority)"]
env_colors = ["#7570b3", "#1b9e77"]
rx_map = {"af41": 1, "af42": 2, "af43": 3}
_yellow = 9.0 - 8.0
THEORY = {
    "sp":      {"af41": 8.0, "af42": _yellow*2/3, "af43": _yellow*1/3},
    "uniform": {"af41": 4/7*9, "af42": 2/7*9, "af43": 1/7*9},
}
MODE_EN = {"sp": "SP enabled", "uniform": "SP disabled (uniform prio)"}

# scenario key -> (folder, legend label, filename suffix, shade failure window)
SCENARIOS = {
    "normal":          ("frr_normal", "normal", "", False),
    "failure":         ("frr_failure", "failure (no reroute)", "_failure", True),
    "failure_reroute": ("frr_failure_reroute", "failure (auto-reroute)", "_reroute", True),
}
FAILURE_WINDOW = (20, 40)
# scenario styling (key, legend label, color, linestyle) — matches plot_frr.py
SC_STYLE = [
    ("normal",          "Normal",                 "#4CAE4C", "-"),
    ("failure",         "Failure (no reroute)",   "#DC4748", "--"),
    ("failure_reroute", "Failure (auto-reroute)", "#418BBF", "-."),
]

def env_names_for(mode):
    return [c[0].replace("\n", " ") for c in CONDITIONS[mode]]

def plot_owd_timeseries(mode):
    enames = env_names_for(mode)
    fig, axes = plt.subplots(3, 1, figsize=(7.0, 7.2), sharex=True)
    for ax, cls, clab in zip(axes, cls_keys, cls_labels):
        for env_idx, (ename, ecol) in enumerate(zip(enames, env_colors)):
            folder = CONDITIONS[mode][env_idx][1]
            t, ms = parse_owd_series(folder, cls)
            ax.plot(t, ms, color=ecol, linewidth=1.0, label=ename)
        ax.set_ylabel("OWD [ms]")
        ax.set_title(clab, loc="left", fontsize=12)
        ax.set_xlim(0, 60); ax.grid(axis="both")
        headroom_linear(ax, bottom=0)
    axes[0].legend(loc="upper right", title="Environment", ncol=2)
    axes[-1].set_xlabel("Elapsed time [s]")
    fig.suptitle(f"One-Way Delay over Time: Simulation (veth) vs Hardware (C2)  "
                 f"({MODE_EN[mode]}, normal)", fontsize=13)
    fig.tight_layout()
    stem = "fig_owd_sim_vs_real" if mode == "sp" else "fig_owd_timeseries_uniform"
    fig.savefig(OUT_DIR / f"{stem}.png"); fig.savefig(OUT_DIR / f"{stem}.pdf")
    plt.close(fig); print(f"[*] {stem}")

def plot_throughput_timeseries(mode, scenario="normal"):
    sc_folder, sc_en, sc_sfx, shade = SCENARIOS[scenario]
    enames = env_names_for(mode)
    fig, axes = plt.subplots(3, 1, figsize=(7.0, 7.2), sharex=True)
    for ax, cls, clab in zip(axes, cls_keys, cls_labels):
        if shade:
            ax.axvspan(*FAILURE_WINDOW, color="#d95f0e", alpha=0.08,
                       label="Failure window (t=20–40 s)")
        for env_idx, (ename, ecol) in enumerate(zip(enames, env_colors)):
            folder = CONDITIONS[mode][env_idx][1]
            t, g = parse_throughput_series(folder, rx_map[cls], sc_folder)
            ax.plot(t, g, color=ecol, linewidth=1.2, label=ename)
        ax.axhline(THEORY[mode][cls], color="0.4", linestyle=":", linewidth=1.1,
                   label=f"Theoretical {THEORY[mode][cls]:.2f} Gbps")
        ax.set_ylabel("Throughput [Gbps]")
        ax.set_title(clab, loc="left", fontsize=12)
        ax.set_xlim(0, 60); ax.grid(axis="both")
        headroom_linear(ax, bottom=0)
    axes[0].legend(loc="center right", fontsize=10, ncol=1)
    axes[-1].set_xlabel("Elapsed time [s]")
    fig.suptitle(f"Received Throughput over Time: Simulation (veth) vs Hardware (C2)  "
                 f"({MODE_EN[mode]}, {sc_en})", fontsize=13)
    fig.tight_layout()
    stem = "fig_throughput_timeseries" + ("" if mode == "sp" else "_uniform") + sc_sfx
    fig.savefig(OUT_DIR / f"{stem}.png"); fig.savefig(OUT_DIR / f"{stem}.pdf")
    plt.close(fig); print(f"[*] {stem}")

def plot_scenario_comparison(mode, env_idx=1):
    folder = CONDITIONS[mode][env_idx][1]
    env_label = env_names_for(mode)[env_idx]
    fig, axes = plt.subplots(3, 1, figsize=(7.2, 7.4), sharex=True)
    for ax, cls, clab in zip(axes, cls_keys, cls_labels):
        ax.axvspan(*FAILURE_WINDOW, color="#d95f0e", alpha=0.07)
        for sc_key, sc_lab, scol, sls in SC_STYLE:
            t, g = parse_throughput_series(folder, rx_map[cls], SCENARIOS[sc_key][0])
            ax.plot(t, g, color=scol, linestyle=sls, linewidth=1.5, label=sc_lab)
        ax.axhline(THEORY[mode][cls], color="0.5", linestyle=":", linewidth=1.0)
        ax.set_ylabel("Throughput [Gbps]")
        ax.set_title(clab, loc="left", fontsize=12)
        ax.set_xlim(0, 60); ax.grid(axis="both")
        headroom_linear(ax, bottom=0)
    axes[0].legend(loc="center right", fontsize=10, ncol=1)
    axes[-1].set_xlabel("Elapsed time [s]")
    fig.suptitle(f"Per-scenario Throughput ({env_label}, {MODE_EN[mode]})\n"
                 f"Failure window t=20–40 s shaded", fontsize=13)
    fig.tight_layout()
    stem = "fig_scenario_comparison" + ("" if mode == "sp" else "_uniform")
    fig.savefig(OUT_DIR / f"{stem}.png"); fig.savefig(OUT_DIR / f"{stem}.pdf")
    plt.close(fig); print(f"[*] {stem}")

def plot_scenario_comparison_combined(env_idx=1):
    folder_of = {m: CONDITIONS[m][env_idx][1] for m in ("sp", "uniform")}
    env_label = env_names_for("sp")[env_idx]
    modes = ["sp", "uniform"]
    fig, axes = plt.subplots(3, 2, figsize=(12.0, 7.6), sharex=True)
    for row, (cls, clab) in enumerate(zip(cls_keys, cls_labels)):
        for col, mode in enumerate(modes):
            ax = axes[row][col]
            ax.axvspan(*FAILURE_WINDOW, color="#d95f0e", alpha=0.07)
            for sc_key, sc_lab, scol, sls in SC_STYLE:
                t, g = parse_throughput_series(folder_of[mode], rx_map[cls],
                                               SCENARIOS[sc_key][0])
                ax.plot(t, g, color=scol, linestyle=sls, linewidth=1.4, label=sc_lab)
            ax.axhline(THEORY[mode][cls], color="0.5", linestyle=":", linewidth=1.0)
            ax.set_xlim(0, 60); ax.grid(axis="both")
            headroom_linear(ax, bottom=0)
            if row == 0:
                ax.set_title(MODE_EN[mode], fontsize=13, pad=6)
            if col == 0:
                ax.set_ylabel(f"{clab}\nThroughput [Gbps]")
    for col in range(2):
        axes[-1][col].set_xlabel("Elapsed time [s]")
    axes[0][1].legend(loc="upper right", fontsize=10, ncol=1)
    fig.suptitle(f"Per-scenario Throughput — SP enabled vs disabled "
                 f"({env_label}, failure window t=20–40 s shaded)", fontsize=14)
    fig.tight_layout()
    stem = "fig_scenario_comparison_combined"
    fig.savefig(OUT_DIR / f"{stem}.png"); fig.savefig(OUT_DIR / f"{stem}.pdf")
    plt.close(fig); print(f"[*] {stem}")

def plot_owd_comparison_combined(env_idx=1):
    folder_of = {m: CONDITIONS[m][env_idx][1] for m in ("sp", "uniform")}
    env_label = env_names_for("sp")[env_idx]
    modes = ["sp", "uniform"]
    fig, axes = plt.subplots(3, 2, figsize=(12.0, 7.6), sharex=True)
    for row, (cls, clab) in enumerate(zip(cls_keys, cls_labels)):
        for col, mode in enumerate(modes):
            ax = axes[row][col]
            ax.axvspan(*FAILURE_WINDOW, color="#d95f0e", alpha=0.07)
            for sc_key, sc_lab, scol, sls in SC_STYLE:
                xb, yb = parse_owd_binned(folder_of[mode], cls, SCENARIOS[sc_key][0])
                ax.plot(xb, yb, color=scol, linestyle=sls, linewidth=1.4, label=sc_lab)
            ax.set_xlim(0, 60); ax.grid(axis="both")
            headroom_linear(ax, bottom=0)
            if row == 0:
                ax.set_title(MODE_EN[mode], fontsize=13, pad=6)
            if col == 0:
                ax.set_ylabel(f"{clab}\nOWD [ms]")
    for col in range(2):
        axes[-1][col].set_xlabel("Elapsed time [s]")
    axes[0][1].legend(loc="upper right", fontsize=10, ncol=1)
    fig.suptitle(f"Per-scenario One-Way Delay — SP enabled vs disabled "
                 f"({env_label}, failure window t=20–40 s, 1 s median)", fontsize=14)
    fig.tight_layout()
    stem = "fig_owd_comparison_combined"
    fig.savefig(OUT_DIR / f"{stem}.png"); fig.savefig(OUT_DIR / f"{stem}.pdf")
    plt.close(fig); print(f"[*] {stem}")

def plot_scenario_comparison_shared(env_idx=1):
    from matplotlib.lines import Line2D
    folder_of = {m: CONDITIONS[m][env_idx][1] for m in ("sp", "uniform")}
    env_label = env_names_for("sp")[env_idx]
    sc_color = {k: c for (k, lab, c, ls) in SC_STYLE}
    sc_en    = {k: lab for (k, lab, c, ls) in SC_STYLE}
    mode_ls  = {"sp": "-", "uniform": "--"}
    fig, axes = plt.subplots(3, 1, figsize=(7.6, 7.8), sharex=True)
    for ax, cls, clab in zip(axes, cls_keys, cls_labels):
        ax.axvspan(*FAILURE_WINDOW, color="#d95f0e", alpha=0.07)
        for mode in ("sp", "uniform"):
            for sc_key in ("normal", "failure", "failure_reroute"):
                t, g = parse_throughput_series(folder_of[mode], rx_map[cls],
                                               SCENARIOS[sc_key][0])
                ax.plot(t, g, color=sc_color[sc_key], linestyle=mode_ls[mode], linewidth=1.4)
        ax.set_ylabel("Throughput [Gbps]")
        ax.set_title(clab, loc="left", fontsize=12)
        ax.set_xlim(0, 60); ax.grid(axis="both")
        headroom_linear(ax, bottom=0)
    axes[-1].set_xlabel("Elapsed time [s]")
    color_handles = [Line2D([0], [0], color=sc_color[k], lw=2.2, label=sc_en[k])
                     for k in ("normal", "failure", "failure_reroute")]
    style_handles = [Line2D([0], [0], color="0.3", lw=1.8, linestyle="-",  label="SP enabled"),
                     Line2D([0], [0], color="0.3", lw=1.8, linestyle="--", label="SP disabled")]
    leg1 = axes[0].legend(handles=color_handles, loc="upper right",
                          fontsize=10, title="Scenario (color)")
    axes[0].add_artist(leg1)
    axes[0].legend(handles=style_handles, loc="lower right",
                   fontsize=10, title="SP mode (line style)")
    fig.suptitle(f"Received Throughput — SP enabled/disabled overlaid on shared axis\n"
                 f"({env_label}, failure window t=20–40 s shaded)", fontsize=13)
    fig.tight_layout()
    stem = "fig_scenario_comparison_shared"
    fig.savefig(OUT_DIR / f"{stem}.png"); fig.savefig(OUT_DIR / f"{stem}.pdf")
    plt.close(fig); print(f"[*] {stem}")

def plot_owd_comparison_shared(env_idx=1):
    from matplotlib.lines import Line2D
    folder_of = {m: CONDITIONS[m][env_idx][1] for m in ("sp", "uniform")}
    env_label = env_names_for("sp")[env_idx]
    sc_color = {k: c for (k, lab, c, ls) in SC_STYLE}
    sc_en    = {k: lab for (k, lab, c, ls) in SC_STYLE}
    mode_ls  = {"sp": "-", "uniform": "--"}
    fig, axes = plt.subplots(3, 1, figsize=(7.6, 7.8), sharex=True)
    for ax, cls, clab in zip(axes, cls_keys, cls_labels):
        ax.axvspan(*FAILURE_WINDOW, color="#d95f0e", alpha=0.07)
        for mode in ("sp", "uniform"):
            for sc_key in ("normal", "failure", "failure_reroute"):
                xb, yb = parse_owd_binned(folder_of[mode], cls, SCENARIOS[sc_key][0])
                ax.plot(xb, yb, color=sc_color[sc_key], linestyle=mode_ls[mode], linewidth=1.4)
        ax.set_yscale("log")
        ax.set_ylabel("OWD [ms]")
        ax.set_title(clab, loc="left", fontsize=12)
        ax.set_xlim(0, 60); ax.grid(axis="both", which="both")
        headroom_log(ax, factor=2.2)
    axes[-1].set_xlabel("Elapsed time [s]")
    color_handles = [Line2D([0], [0], color=sc_color[k], lw=2.2, label=sc_en[k])
                     for k in ("normal", "failure", "failure_reroute")]
    style_handles = [Line2D([0], [0], color="0.3", lw=1.8, linestyle="-",  label="SP enabled"),
                     Line2D([0], [0], color="0.3", lw=1.8, linestyle="--", label="SP disabled")]
    leg1 = axes[0].legend(handles=color_handles, loc="upper right",
                          fontsize=10, title="Scenario (color)")
    axes[0].add_artist(leg1)
    axes[0].legend(handles=style_handles, loc="lower right",
                   fontsize=10, title="SP mode (line style)")
    fig.suptitle(f"One-Way Delay — SP enabled/disabled overlaid on shared log axis\n"
                 f"({env_label}, failure window t=20–40 s, 1 s median)", fontsize=13)
    fig.tight_layout()
    stem = "fig_owd_comparison_shared"
    fig.savefig(OUT_DIR / f"{stem}.png"); fig.savefig(OUT_DIR / f"{stem}.pdf")
    plt.close(fig); print(f"[*] {stem}")

# ── Generate all figures ───────────────────────────────────────────────────
for _mode in ("sp", "uniform"):
    plot_owd_timeseries(_mode)
    for _sc in ("normal", "failure", "failure_reroute"):
        plot_throughput_timeseries(_mode, _sc)
    plot_scenario_comparison(_mode)
plot_scenario_comparison_combined()
plot_scenario_comparison_shared()
plot_owd_comparison_combined()
plot_owd_comparison_shared()

print("\n=== AF41 loss rate (from data) ===")
for mode in ("sp", "uniform"):
    print(f"  [{mode}]", ", ".join(
        f"{lbl.splitlines()[0]}={loss:.4f}%" for (lbl, g, loss) in data[mode]["af41"]))
