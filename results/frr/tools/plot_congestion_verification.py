#!/usr/bin/env python3
"""Plot measured evidence that the shared 9-Gbps path was congested.

Data:
  - Aggregate received throughput, averaged over t=5--18 s.
  - tc/HTB queue-drop events at LER_Ingress -> Router 1 over the same window.

The drop counter is reported in GSO-aggregated skb events, not UDP datagrams.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np


BASE = Path(__file__).resolve().parent.parent
DATASETS = {
    "SP + WRR": BASE / "qos/c2/20260721_c2_sp_enabled" / "frr_normal",
    "WRR-only": BASE / "qos/c2/20260721_c2_sp_uniform" / "frr_normal",
}
COLORS = {
    "Offered load": "#777777",
    "SP + WRR": "#418BBF",
    "WRR-only": "#DC4748",
}
T_LO, T_HI = 5, 18
OFFERED_GBPS = 24.0
CAPACITY_GBPS = 9.0


def aggregate_throughput_gbps(path: Path) -> float:
    values: list[float] = []
    seen: set[int] = set()
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            t = int(row["time"])
            if t in seen or not T_LO <= t <= T_HI:
                continue
            seen.add(t)
            total_bytes_per_sec = sum(
                float(row[column])
                for column in (
                    "rx1_bytes_per_sec",
                    "rx2_bytes_per_sec",
                    "rx3_bytes_per_sec",
                )
            )
            values.append(total_bytes_per_sec * 8 / 1e9)
    if not values:
        raise RuntimeError(f"No throughput samples in {path}")
    return float(np.mean(values))


def router1_drop_events_per_sec(path: Path) -> float:
    totals: dict[int, float] = {}
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            t = int(row["time"])
            if not T_LO <= t <= T_HI:
                continue
            if row["node"] != "LER_Ingress" or row["iface"] != "leri-cr1":
                continue
            totals[t] = totals.get(t, 0.0) + float(row["drops_per_sec"])
    if not totals:
        raise RuntimeError(f"No Router 1 drop samples in {path}")
    return float(np.mean(list(totals.values())))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--outdir",
        type=Path,
        default=BASE / "qos/c2/20260721_c2_sp_enabled" / "en",
    )
    args = parser.parse_args()

    throughput = {
        label: aggregate_throughput_gbps(directory / "throughput.csv")
        for label, directory in DATASETS.items()
    }
    drops = {
        label: router1_drop_events_per_sec(directory / "tc_drops.csv")
        for label, directory in DATASETS.items()
    }

    matplotlib.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.24,
            "grid.linestyle": ":",
            "font.size": 12,
            "axes.labelsize": 12,
            "axes.titlesize": 13,
            "xtick.labelsize": 10.5,
            "ytick.labelsize": 10.5,
        }
    )

    fig, (ax_rate, ax_drop) = plt.subplots(
        1,
        2,
        figsize=(9.2, 3.45),
        gridspec_kw={"width_ratios": [1.35, 1.0]},
        layout="constrained",
    )

    # (a) Offered load versus observed aggregate throughput.
    rate_labels = ["Offered\nload", "SP + WRR\nobserved", "WRR-only\nobserved"]
    rate_values = [
        OFFERED_GBPS,
        throughput["SP + WRR"],
        throughput["WRR-only"],
    ]
    rate_colors = [
        COLORS["Offered load"],
        COLORS["SP + WRR"],
        COLORS["WRR-only"],
    ]
    x = np.arange(len(rate_labels))
    bars = ax_rate.bar(x, rate_values, width=0.62, color=rate_colors, zorder=3)
    ax_rate.axhspan(CAPACITY_GBPS, 26, color="#FCE5E5", alpha=0.55, zorder=0)
    ax_rate.axhline(
        CAPACITY_GBPS,
        color="#222222",
        linewidth=1.5,
        linestyle="--",
        zorder=4,
    )
    ax_rate.text(
        2.42,
        CAPACITY_GBPS + 0.45,
        "9-Gbps bottleneck",
        ha="right",
        va="bottom",
        fontsize=10.5,
        fontweight="bold",
    )
    for bar, value in zip(bars, rate_values):
        label = f"{value:.0f}" if value == OFFERED_GBPS else f"{value:.3f}"
        ax_rate.text(
            bar.get_x() + bar.get_width() / 2,
            value - 0.75,
            label,
            ha="center",
            va="top",
            fontsize=11,
            fontweight="bold",
            color="white",
        )
    ax_rate.set_xticks(x, rate_labels)
    ax_rate.set_ylim(0, 26)
    ax_rate.set_ylabel("Traffic rate (Gbps)")
    ax_rate.set_title("(a) Offered versus observed traffic", loc="left", fontweight="bold")
    ax_rate.grid(axis="x", visible=False)

    # (b) Direct queue-drop evidence at the Router 1 bottleneck.
    policy_labels = list(DATASETS)
    drop_values_k = [drops[label] / 1e3 for label in policy_labels]
    x2 = np.arange(len(policy_labels))
    bars2 = ax_drop.bar(
        x2,
        drop_values_k,
        width=0.58,
        color=[COLORS[label] for label in policy_labels],
        zorder=3,
    )
    for bar, value in zip(bars2, drop_values_k):
        ax_drop.text(
            bar.get_x() + bar.get_width() / 2,
            value + 3.0,
            f"{value:.1f}",
            ha="center",
            va="bottom",
            fontsize=11,
            fontweight="bold",
        )
    ax_drop.set_xticks(x2, policy_labels)
    ax_drop.set_ylim(0, 165)
    ax_drop.set_ylabel("Queue-drop counter\n(10³ events/s)")
    ax_drop.set_title("(b) Drops at Router 1", loc="left", fontweight="bold")
    ax_drop.grid(axis="x", visible=False)

    fig.suptitle(
        "",#タイトル
        fontsize=14.5,
        fontweight="bold",
    )
    fig.text(
        0.5,
        0.002,
        "",#フッターに文字挿入
        ha="center",
        va="bottom",
        fontsize=8.3,
        color="#555555",
    )

    args.outdir.mkdir(parents=True, exist_ok=True)
    for extension in ("png", "pdf", "svg"):
        output = args.outdir / f"congestion_verification.{extension}"
        fig.savefig(output, dpi=300, bbox_inches="tight", facecolor="white")
        print(output)

    print(
        f"SP+WRR: throughput={throughput['SP + WRR']:.3f} Gbps, "
        f"drops={drops['SP + WRR']:.0f} events/s"
    )
    print(
        f"WRR-only: throughput={throughput['WRR-only']:.3f} Gbps, "
        f"drops={drops['WRR-only']:.0f} events/s"
    )


if __name__ == "__main__":
    main()
