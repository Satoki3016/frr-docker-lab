import json
import re
import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np

# 日本語フォント設定
_ja_fonts = ["Noto Sans CJK JP", "Noto Sans CJK SC", "Noto Sans CJK TC",
             "TakaoPGothic", "IPAPGothic", "VL PGothic"]
for _f in _ja_fonts:
    if any(_f.lower() in p.name.lower() for p in fm.fontManager.ttflist):
        matplotlib.rcParams["font.family"] = _f
        break

def read_lab_config():
    """lab_config.sh からデフォルト値を読み込む"""
    config_path = Path(__file__).resolve().parent.parent / "scripts" / "lab_config.sh"
    cfg = {}
    if not config_path.exists():
        return cfg
    for line in config_path.read_text().splitlines():
        # CR1_BW="${CR1_BW:-10mbit}" 形式をパース
        m = re.match(r'^(\w+)="\$\{\w+:-(.+)\}"', line.strip())
        if m:
            cfg[m.group(1)] = m.group(2)
    return cfg

# =========================
# 軸の設定（ここを編集）
# None なら自動、数値なら固定
# =========================

# Throughput (Mbit/s)
THR_X_MIN = 0
THR_X_MAX = 60   # 計測時間(s)
THR_Y_MIN = 0
THR_Y_MAX = None  # 自動スケール

# Delay (RTT ms)
DLY_X_MIN = 0
DLY_X_MAX = 60
DLY_Y_MIN = 0
DLY_Y_MAX = None  # 自動スケール (全体図)

# ズーム図: 平常時の遅延を見やすくするため Y 軸上限を自動クリップ
# "auto" → 全データの 95 パーセンタイル × 1.2 を上限に設定
# 数値 → その値を固定上限にする (例: 200)
DLY_Y_ZOOM = "auto"

# 障害区間の設定 (failure シナリオのみ描画)
# None にすると描画しない
FAILURE_START = 20   # 障害開始 (s)
FAILURE_END   = 40   # 障害終了 (s)

# RSVP-TE ingress police 適用タイミング (failure_rsvp のみ)
# rsvp_monitor は 1s ポーリングで検知→即時 ECMP/police 更新
POLICE_DOWN = 21   # 2-link police 適用: 障害検知 ~1s後
POLICE_UP   = 41   # 3-link police 復旧: 復旧検知 ~1s後

# 画像のDPI
FIG_DPI = 200

# =========================
# 解析関数
# =========================

def load_csv_throughput(csv_path: Path, col_idx: int):
    """throughput.csv から時系列スループットを読む
    col_idx: 1=Rx1, 2=Rx2, 3=Rx3 (0列目はtime)
    """
    t = []
    mbps = []
    for line in csv_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("time") or not line.strip():
            continue
        parts = line.split(",")
        if len(parts) <= col_idx:
            continue
        try:
            t.append(float(parts[0]))
            mbps.append(int(parts[col_idx]) * 8 / 1e6)  # bytes/s → Mbit/s
        except (ValueError, IndexError):
            continue
    return t, mbps

def load_iperf_server_throughput(json_path: Path):
    raw = json_path.read_text(encoding="utf-8", errors="ignore")
    # iperf3 が先頭にエラーメッセージを出力する場合があるので JSON 部分のみ抽出
    start_idx = raw.find("{")
    if start_idx > 0:
        raw = raw[start_idx:]
    d = json.loads(raw)

    # サーバ側JSON (--one-off で収集): intervals の sum が受信量
    # sender=false の intervals を優先 (受信量); なければ全 intervals を使用
    intervals = d.get("intervals", [])
    recv_intervals = [itv for itv in intervals
                      if not itv.get("sum", {}).get("sender", True)]
    if recv_intervals:
        intervals = recv_intervals

    t = []
    mbps = []
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

def load_ping_rtt(log_path: Path):
    ts = []
    rtt = []
    for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = PING_RE.match(line.strip())
        if not m:
            continue
        ts.append(float(m.group("ts")))
        rtt.append(float(m.group("rtt")))
    if not ts:
        return [], []
    t0 = ts[0]
    rel = [x - t0 for x in ts]
    return rel, rtt

def find_file(outdir: Path, candidates):
    for name in candidates:
        p = outdir / name
        if p.exists():
            return p
    return None

def add_failure_zone(ax, x_max, rsvp=False):
    """障害区間を赤帯で表示する"""
    if FAILURE_START is None or FAILURE_END is None:
        return
    rsvp_note = " + RSVP-TE reroute" if rsvp else ""
    ax.axvspan(FAILURE_START, FAILURE_END,
               alpha=0.15, color="red", label=f"Failure zone (leri-cr1 Down{rsvp_note})")
    ax.axvline(FAILURE_START, color="red", linestyle="--", linewidth=1.0, alpha=0.7)
    ax.axvline(FAILURE_END,   color="blue", linestyle="--", linewidth=1.0, alpha=0.7)
    y_top = ax.get_ylim()[1]
    ax.text(FAILURE_START + 0.5, y_top * 0.96,
            "↓ Link Down", color="red", fontsize=8, va="top")
    ax.text(FAILURE_END + 0.5, y_top * 0.96,
            "↑ Link Up", color="blue", fontsize=8, va="top")
    if rsvp and POLICE_DOWN is not None:
        ax.axvline(POLICE_DOWN, color="darkorange", linestyle=":", linewidth=1.2, alpha=0.8)
        ax.axvline(POLICE_UP,   color="green",      linestyle=":", linewidth=1.2, alpha=0.8)
        ax.text(POLICE_DOWN + 0.3, y_top * 0.82,
                "Police\n2-link", color="darkorange", fontsize=7, va="top")
        ax.text(POLICE_UP + 0.3, y_top * 0.82,
                "Police\n3-link", color="green", fontsize=7, va="top")

# =========================
# メイン
# =========================

def main(outdir: Path):
    pairs = [("Rx1", "Tx1"), ("Rx2", "Tx2"), ("Rx3", "Tx3")]
    colors = ["tab:blue", "tab:orange", "tab:green"]

    cfg = read_lab_config()
    labels = [
        f"Rx1 AF41 High   CR1:{cfg.get('CR1_BW','?')} delay:{cfg.get('CR1_DELAY','?')} TX:{cfg.get('TX1_RATE','?')}",
        f"Rx2 AF42 Medium CR2:{cfg.get('CR2_BW','?')} delay:{cfg.get('CR2_DELAY','?')} TX:{cfg.get('TX2_RATE','?')}",
        f"Rx3 AF43 Low    CR3:{cfg.get('CR3_BW','?')} delay:{cfg.get('CR3_DELAY','?')} TX:{cfg.get('TX3_RATE','?')}",
    ]

    # シナリオ判定 (ディレクトリ名で判断)
    is_failure      = outdir.name in ("failure", "failure_rsvp")
    is_failure_rsvp = outdir.name == "failure_rsvp"

    # データ読み込み
    thr_data = []   # (label, t, mbps)
    dly_data = []   # (label, t, rtt)

    csv_path = outdir / "throughput.csv"

    for i, ((rx, tx), label, color) in enumerate(zip(pairs, labels, colors)):
        ping_candidates = [
            f"{tx}_ping.log", f"{tx.lower()}_ping.log",
            f"{tx}.log",      f"{tx.lower()}.log",
        ]

        # スループット: CSV 優先、なければ iperf3 JSON にフォールバック
        if csv_path.exists():
            t, mbps = load_csv_throughput(csv_path, i + 1)
            if t:
                thr_data.append((label, t, mbps, color))
            else:
                print(f"[!] throughput.csv に {rx} のデータがありません")
        else:
            iperf_candidates = [
                f"{rx}_server.json", f"{rx.lower()}_server.json",
                f"{rx}.json",        f"{rx.lower()}.json",
            ]
            iperf_json = find_file(outdir, iperf_candidates)
            if iperf_json is None:
                print(f"[!] missing iperf json for {rx}: tried {iperf_candidates}")
            else:
                try:
                    t, mbps = load_iperf_server_throughput(iperf_json)
                    thr_data.append((label, t, mbps, color))
                except Exception as e:
                    print(f"[!] iperf JSON 読み込み失敗 ({rx}): {e}")

        ping_log = find_file(outdir, ping_candidates)
        if ping_log is None:
            print(f"[!] missing ping log for {tx}->{rx}: tried {ping_candidates}")
        else:
            t, rtt = load_ping_rtt(ping_log)
            dly_data.append((f"{tx}->{rx}", t, rtt, color))

    if is_failure_rsvp:
        scenario_title = "[Failure + RSVP-TE Scenario]"
    elif is_failure:
        scenario_title = "[Failure Scenario]"
    else:
        scenario_title = "[Normal Scenario]"

    # パケットロスグラフ (ping/throughput の有無に関わらず生成)
    plot_packet_loss(outdir, scenario_title)

    # --------------------------------------------------
    # スループット: Rx1/Rx2/Rx3 を1枚に重ねて描画
    # --------------------------------------------------
    if thr_data:
        fig, ax = plt.subplots(figsize=(10, 5))
        for label, t, mbps, color in thr_data:
            ax.plot(t, mbps, label=label, color=color)
        if THR_X_MIN is not None or THR_X_MAX is not None:
            ax.set_xlim(left=THR_X_MIN, right=THR_X_MAX)
        if THR_Y_MIN is not None or THR_Y_MAX is not None:
            ax.set_ylim(bottom=THR_Y_MIN, top=THR_Y_MAX)
        if is_failure:
            add_failure_zone(ax, THR_X_MAX, rsvp=is_failure_rsvp)
        ax.set_title(f"{scenario_title} Throughput (iperf3 UDP received)")
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Throughput (Mbit/s)")
        ax.legend()
        ax.grid(True)
        out = outdir / "Docker_all_throughput.png"
        fig.savefig(out, dpi=FIG_DPI, bbox_inches="tight")
        plt.close(fig)
        print(f"[*] saved: {out}")

    # --------------------------------------------------
    # 遅延: Tx1->Rx1 / Tx2->Rx2 / Tx3->Rx3 を1枚に
    # --------------------------------------------------
    if dly_data:
        def _plot_delay(ax, y_top=None, title_suffix=""):
            for label, t, rtt, color in dly_data:
                ax.plot(t, rtt, label=label, color=color, alpha=0.8)
            ax.set_xlim(left=DLY_X_MIN, right=DLY_X_MAX)
            ax.set_ylim(bottom=DLY_Y_MIN, top=y_top)
            if is_failure:
                add_failure_zone(ax, DLY_X_MAX, rsvp=is_failure_rsvp)
            ax.set_title(f"{scenario_title} End-to-End Delay (ping RTT){title_suffix}")
            ax.set_xlabel("Time (s)")
            ax.set_ylabel("RTT (ms)")
            ax.legend()
            ax.grid(True)

        # 全体図
        fig, ax = plt.subplots(figsize=(10, 5))
        _plot_delay(ax)
        out = outdir / "Docker_all_delay_rtt.png"
        fig.savefig(out, dpi=FIG_DPI, bbox_inches="tight")
        plt.close(fig)
        print(f"[*] saved: {out}")

        # ズーム図 (平常時の遅延を見やすくする)
        all_rtt_vals = [v for _, _, rtt, _ in dly_data for v in rtt]
        if all_rtt_vals:
            if DLY_Y_ZOOM == "auto":
                zoom_top = float(np.percentile(all_rtt_vals, 95)) * 1.2
            else:
                zoom_top = float(DLY_Y_ZOOM)
            fig, ax = plt.subplots(figsize=(10, 5))
            _plot_delay(ax, y_top=zoom_top,
                        title_suffix=f"  [zoom ≤{zoom_top:.0f}ms / peaks clipped]")
            out_zoom = outdir / "Docker_all_delay_rtt_zoom.png"
            fig.savefig(out_zoom, dpi=FIG_DPI, bbox_inches="tight")
            plt.close(fig)
            print(f"[*] saved: {out_zoom}  (y_max={zoom_top:.0f}ms, 95th-pct clip)")

def _parse_rate_mbps(rate_str: str) -> float:
    """'500M' / '100M' / '10mbit' などを Mbps float に変換"""
    s = rate_str.strip().upper().rstrip("BIT").rstrip("B")
    if s.endswith("G"):
        return float(s[:-1]) * 1000
    if s.endswith("M"):
        return float(s[:-1])
    if s.endswith("K"):
        return float(s[:-1]) / 1000
    return float(s) / 1e6  # bps と仮定


def plot_packet_loss(outdir: Path, scenario_title: str):
    """packet_loss.csv + throughput.csv から優先度別ロスを3パネルで表示"""
    csv_path = outdir / "packet_loss.csv"
    if not csv_path.exists():
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
                "node":    parts[0],
                "iface":   parts[1],
                "dir":     parts[2],
                "cls":     parts[3],
                "sent":    int(parts[4]),
                "dropped": int(parts[5]),
            })
        except ValueError:
            continue

    if not rows:
        return

    classes    = ["AF41(高)", "AF42(中)", "AF43(低)"]
    cls_colors = {"AF41(高)": "tab:blue", "AF42(中)": "tab:orange", "AF43(低)": "tab:green"}

    def aggregate(direction, node_filter=None):
        result = {}
        for cls in classes:
            matched = [r for r in rows
                       if r["cls"] == cls and r["dir"] == direction
                       and (node_filter is None or node_filter in r["node"])]
            total_sent    = sum(r["sent"]    for r in matched)
            total_dropped = sum(r["dropped"] for r in matched)
            total = total_sent + total_dropped
            loss_pct = total_dropped / total * 100 if total > 0 else 0.0
            result[cls] = {"sent": total_sent, "dropped": total_dropped, "loss": loss_pct}
        return result

    ler_eg = aggregate("egress", node_filter="LER_Ingress_ns")
    cr_eg  = aggregate("egress", node_filter="CoreRouter")

    # TX対比の総ロス率: throughput.csv の平均受信スループット vs 送信レート
    cfg = read_lab_config()
    tx_rates_mbps = [
        _parse_rate_mbps(cfg.get("TX1_RATE", "500M")),
        _parse_rate_mbps(cfg.get("TX2_RATE", "500M")),
        _parse_rate_mbps(cfg.get("TX3_RATE", "500M")),
    ]
    e2e_loss = {}
    thr_csv = outdir / "throughput.csv"
    if thr_csv.exists():
        for col_idx, cls, tx_mbps in zip([1, 2, 3], classes, tx_rates_mbps):
            t_vals, mbps_vals = load_csv_throughput(thr_csv, col_idx)
            # 最初と最後の1点を除いて平均 (立ち上がり・立ち下がりを除外)
            if len(mbps_vals) > 4:
                mbps_vals = mbps_vals[1:-1]
            avg_rx = float(np.mean(mbps_vals)) if mbps_vals else 0.0
            loss = max(0.0, (1.0 - avg_rx / tx_mbps) * 100) if tx_mbps > 0 else 0.0
            e2e_loss[cls] = {"avg_rx": avg_rx, "tx": tx_mbps, "loss": loss}

    # ---- 描画 ----
    n_panels = 3 if e2e_loss else 2
    fig, axes = plt.subplots(1, n_panels, figsize=(5 * n_panels, 5))
    fig.suptitle(f"{scenario_title}  Packet Loss by Priority", fontsize=12, fontweight="bold")

    def draw_bar_panel(ax, data, title):
        vals   = [data[c]["loss"]    for c in classes]
        drops  = [data[c]["dropped"] for c in classes]
        colors = [cls_colors[c]      for c in classes]
        bars = ax.bar(classes, vals, color=colors, edgecolor="white", width=0.5)
        for bar, loss, dropped in zip(bars, vals, drops):
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 0.5,
                    f"{loss:.1f}%\n({dropped:,} pkt)",
                    ha="center", va="bottom", fontsize=9, fontweight="bold")
        ax.set_ylabel("Packet Loss (%)")
        ax.set_title(title, fontsize=9)
        ax.set_ylim(0, max(vals) * 1.3 + 5 if max(vals) > 0 else 10)
        ax.grid(axis="y", alpha=0.3)
        if len(vals) == 3 and vals[0] < vals[1] < vals[2]:
            ax.text(0.5, 0.97, "✓ Priority OK  AF41<AF42<AF43",
                    transform=ax.transAxes, ha="center", va="top",
                    fontsize=8, color="green", fontweight="bold")
        elif any(v > 0 for v in vals):
            ax.text(0.5, 0.97, "x Priority inversion",
                    transform=ax.transAxes, ha="center", va="top",
                    fontsize=8, color="red", fontweight="bold")

    draw_bar_panel(axes[0], ler_eg,
                   "LER_Ingress WRR HTB\n(輻輳時ドロップ率)")
    draw_bar_panel(axes[1], cr_eg,
                   "CoreRouter HTB\n(追加ドロップ率)")

    if e2e_loss:
        ax = axes[2]
        vals   = [e2e_loss[c]["loss"]   for c in classes]
        rx_avg = [e2e_loss[c]["avg_rx"] for c in classes]
        colors = [cls_colors[c]         for c in classes]
        bars = ax.bar(classes, vals, color=colors, edgecolor="white", width=0.5)
        for bar, loss, rx in zip(bars, vals, rx_avg):
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 0.5,
                    f"{loss:.1f}%\n(Rx:{rx:.0f}M)",
                    ha="center", va="bottom", fontsize=9, fontweight="bold")
        tx_label = "/".join(f"{t:.0f}M" for t in tx_rates_mbps)
        ax.set_ylabel("End-to-End Loss (%)")
        ax.set_title(f"TX対比 総ロス率\n(TX={tx_label} 基準)", fontsize=9)
        ax.set_ylim(0, max(vals) * 1.1 + 5 if max(vals) > 0 else 100)
        ax.grid(axis="y", alpha=0.3)
        if len(vals) == 3 and vals[0] < vals[1] < vals[2]:
            ax.text(0.5, 0.97, "✓ Priority OK  AF41<AF42<AF43",
                    transform=ax.transAxes, ha="center", va="top",
                    fontsize=8, color="green", fontweight="bold")
        elif any(v > 0 for v in vals):
            ax.text(0.5, 0.97, "x Priority inversion",
                    transform=ax.transAxes, ha="center", va="top",
                    fontsize=8, color="red", fontweight="bold")

    fig.tight_layout()
    out = outdir / "Docker_packet_loss.png"
    fig.savefig(out, dpi=FIG_DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"[*] saved: {out}")


def _baseline_mean(t_vals, mbps_vals, t_start=2, t_end=None):
    """障害前ベースライン平均を計算 (t_end=None → FAILURE_START の 1s 前まで)"""
    if t_end is None:
        t_end = FAILURE_START - 1
    vals = [v for tv, v in zip(t_vals, mbps_vals) if t_start <= tv <= t_end]
    return float(np.mean(vals)) if vals else None


def compare_scenarios(base_dir: Path):
    """3シナリオ比較グラフ (絶対値 + 正規化の2種)"""
    scenarios = [
        ("normal",       "normal",                   "tab:green", "-"),
        ("failure",      "failure (static ECMP)",    "tab:red",   "--"),
        ("failure_rsvp", "failure_rsvp (RSVP-TE)",  "tab:blue",  "-"),
    ]
    rx_labels  = ["Rx1 (AF41 High)", "Rx2 (AF42 Med)", "Rx3 (AF43 Low)"]
    rx_indices = [1, 2, 3]

    # ---- 1枚目: 絶対値 ----
    fig1, axes1 = plt.subplots(3, 1, figsize=(11, 12), sharex=True)
    fig1.suptitle("3-Scenario Comparison  [Absolute Throughput]", fontsize=12)

    # ---- 2枚目: ベースライン正規化 (ECMP ハッシュばらつきを除去) ----
    fig2, axes2 = plt.subplots(3, 1, figsize=(11, 12), sharex=True)
    fig2.suptitle(
        "3-Scenario Comparison  [Normalized to Pre-Failure Baseline]\n"
        "ECMP hash randomness removed — shows true QoS effect",
        fontsize=11,
    )

    for ax1, ax2, rx_idx, rx_label in zip(axes1, axes2, rx_indices, rx_labels):
        for dirname, legend_name, color, ls in scenarios:
            csv_path = base_dir / dirname / "throughput.csv"
            if not csv_path.exists():
                continue
            t, mbps = load_csv_throughput(csv_path, rx_idx)
            if not t:
                continue

            # 絶対値グラフ
            ax1.plot(t, mbps, label=legend_name, color=color, linestyle=ls, linewidth=1.5)

            # 正規化グラフ: failure/failure_rsvp はベースライン比, normal は 100% 基準線
            if dirname == "normal":
                ax2.axhline(100, color=color, linestyle=ls, linewidth=1.2,
                            alpha=0.6, label=legend_name)
            else:
                base = _baseline_mean(t, mbps)
                if base and base > 0:
                    norm = [v / base * 100 for v in mbps]
                    ax2.plot(t, norm, label=f"{legend_name}\n(base={base:.0f}Mbps)",
                             color=color, linestyle=ls, linewidth=1.5)

        for ax in (ax1, ax2):
            ax.axvspan(FAILURE_START, FAILURE_END, alpha=0.08, color="red")
            ax.axvline(FAILURE_START, color="red",  linestyle="--", linewidth=1.0, alpha=0.6)
            ax.axvline(FAILURE_END,   color="blue", linestyle="--", linewidth=1.0, alpha=0.6)
            ax.axvline(POLICE_DOWN, color="darkorange", linestyle=":", linewidth=1.2, alpha=0.7)
            ax.axvline(POLICE_UP,   color="green",      linestyle=":", linewidth=1.2, alpha=0.7)
            ax.set_xlim(0, 60)
            ax.set_title(rx_label)
            ax.legend(fontsize=8)
            ax.grid(True)

        ax1.set_ylabel("Throughput (Mbit/s)")
        ax2.set_ylabel("Throughput (% of pre-failure baseline)")

    for axes in (axes1, axes2):
        axes[0].text(FAILURE_START + 0.3, axes[0].get_ylim()[1] * 0.97,
                     "↓ Down", color="red",  fontsize=7, va="top")
        axes[0].text(FAILURE_END   + 0.3, axes[0].get_ylim()[1] * 0.97,
                     "↑ Up",   color="blue", fontsize=7, va="top")
        axes[-1].set_xlabel("Time (s)")

    fig1.tight_layout()
    out1 = base_dir / "compare_all_scenarios.png"
    fig1.savefig(out1, dpi=FIG_DPI, bbox_inches="tight")
    plt.close(fig1)
    print(f"[*] saved: {out1}")

    fig2.tight_layout()
    out2 = base_dir / "compare_normalized.png"
    fig2.savefig(out2, dpi=FIG_DPI, bbox_inches="tight")
    plt.close(fig2)
    print(f"[*] saved: {out2}")

    # ---- 3枚目: 障害区間の平均ドロップ率バーチャート ----
    _bar_data = {}
    for dirname, legend_name, color, ls in scenarios:
        if dirname == "normal":
            continue
        csv_path = base_dir / dirname / "throughput.csv"
        if not csv_path.exists():
            continue
        drops = []
        for rx_idx in rx_indices:
            t, mbps = load_csv_throughput(csv_path, rx_idx)
            base = _baseline_mean(t, mbps)
            fail = _baseline_mean(t, mbps, t_start=FAILURE_START+1, t_end=FAILURE_END-1)
            if base and base > 0 and fail is not None:
                drops.append((1.0 - fail / base) * 100)
            else:
                drops.append(0.0)
        _bar_data[legend_name] = (color, drops)

    if _bar_data:
        fig3, ax3 = plt.subplots(figsize=(8, 5))
        cls_names = ["AF41\n(High)", "AF42\n(Med)", "AF43\n(Low)"]
        x = np.arange(len(cls_names))
        width = 0.35
        for i, (legend_name, (color, drops)) in enumerate(_bar_data.items()):
            offset = (i - (len(_bar_data) - 1) / 2) * width
            bars = ax3.bar(x + offset, drops, width, label=legend_name,
                           color=color, alpha=0.8, edgecolor="white")
            for bar, v in zip(bars, drops):
                ax3.text(bar.get_x() + bar.get_width() / 2,
                         bar.get_height() + 0.5,
                         f"{v:.1f}%", ha="center", va="bottom", fontsize=9)
        ax3.set_xticks(x)
        ax3.set_xticklabels(cls_names)
        ax3.set_ylabel("Throughput Drop during Failure (%)")
        ax3.set_title(
            "Priority Class Impact during Failure\n"
            "(% drop vs pre-failure baseline, t=20-40s)",
            fontsize=11,
        )
        ax3.legend()
        ax3.grid(axis="y", alpha=0.3)
        all_drops = [v for _, (_, drops) in _bar_data.items() for v in drops]
        ax3.set_ylim(0, max(max(all_drops) * 1.3, 10) + 5)
        # WRR priority annotation
        ax3.text(0.98, 0.98,
                 "Ideal: AF41 < AF42 < AF43\n(high priority drops less)",
                 transform=ax3.transAxes, ha="right", va="top",
                 fontsize=8, color="gray",
                 bbox=dict(boxstyle="round", fc="white", alpha=0.7))
        fig3.tight_layout()
        out3 = base_dir / "compare_priority_drop.png"
        fig3.savefig(out3, dpi=FIG_DPI, bbox_inches="tight")
        plt.close(fig3)
        print(f"[*] saved: {out3}")


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        outdir = Path(sys.argv[1])
    else:
        outdir = Path(__file__).resolve().parent
    main(outdir)
    # 引数がベースディレクトリ (results/) または比較モードのとき
    base = Path(__file__).resolve().parent
    if outdir.resolve() == base or sys.argv[-1] == "--compare":
        compare_scenarios(base)
