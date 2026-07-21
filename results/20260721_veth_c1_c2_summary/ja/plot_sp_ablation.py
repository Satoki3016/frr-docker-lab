"""
plot_sp_ablation.py — SP有効/無効 × veth/C1/C2 の6条件比較図 (査読品質)

主図 : AF41(高優先)パケット損失率のグループ化棒グラフ (対数軸)
補助図: クラス別スループットのグループ化棒グラフ (SP有効/無効の2パネル)

各条件の損失率・スループットは対応する iperf3 receiver ログから直接算出する
(ハードコードせず実データを都度パースするため、再実行で常に最新値になる)。
"""
from pathlib import Path
import re
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np

# 出力(図)はこのスクリプトと同じフォルダ(OUT_DIR)に保存。
# 実験データは常に <project>/results/frr/ にあるため、祖先から "results" を
# 探して frr を辿る(サブフォルダ深さに依らず動く)。
OUT_DIR = Path(__file__).resolve().parent
_results = next(a for a in Path(__file__).resolve().parents if a.name == "results")
DATA_DIR = _results / "frr"

# ── フォント (plot_frr.py と統一) ──────────────────────────────────────
for _f in ["Noto Sans CJK JP", "TakaoPGothic", "IPAPGothic", "VL PGothic"]:
    if any(_f.lower() in p.name.lower() for p in fm.fontManager.ttflist):
        matplotlib.rcParams["font.family"] = _f
        break

matplotlib.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white",
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.linewidth": 0.8, "axes.labelsize": 10, "axes.titlesize": 10,
    "xtick.labelsize": 9, "ytick.labelsize": 9,
    "legend.fontsize": 9, "legend.framealpha": 0.9, "legend.edgecolor": "0.8",
    "grid.alpha": 0.3, "grid.linewidth": 0.5, "grid.linestyle": ":",
    "savefig.dpi": 300, "savefig.bbox": "tight", "savefig.pad_inches": 0.05,
})

import math as _math

def headroom_linear(ax, frac=0.18, bottom=0.0):
    """線形軸: プロット済みデータの最大値より frac 分だけ上に余白を作る。
    (実測値が軸の最大に張り付かないようにする。全図で統一適用)"""
    ymax = 0.0
    for ln in ax.get_lines():
        yd = [v for v in ln.get_ydata() if v is not None and not _math.isnan(v)]
        if yd:
            ymax = max(ymax, max(yd))
    if ymax > 0:
        ax.set_ylim(bottom, ymax * (1.0 + frac))

def headroom_log(ax, factor=2.2, bottom=None):
    """対数軸: プロット済みデータの最大値の factor 倍を上限にする(乗算的な余白)。"""
    ymax = 0.0
    for ln in ax.get_lines():
        yd = [v for v in ln.get_ydata() if v is not None and not _math.isnan(v) and v > 0]
        if yd:
            ymax = max(ymax, max(yd))
    if ymax > 0:
        ax.set_ylim(top=ymax * factor)
    if bottom is not None:
        ax.set_ylim(bottom=bottom)

# ── データソース ───────────────────────────────────────────────────────
# (ラベル, フォルダ, CR帯域Gbps)
# 2026-07-21: 全環境でCR=9G・TX=8G/クラスに統一(vethも9Gで再計測)。
# 図はveth(シミュレーション基準)とC2(実機代表・完全独立3経路)の2環境に絞る。
# C1(共有トランク)はC2とほぼ同一結果のため図からは省略し、
# 比較表(veth_c1_c2_comparison_table.md)にのみ全3環境を記録している。
CONDITIONS = {
    "sp": [
        ("veth\n(C=9G)", "20260721_veth9G_sp_enabled", 9),
        ("C2 (実機)\n(C=9G)", "20260721_c2_sp_enabled", 9),
    ],
    "uniform": [
        ("veth\n(C=9G)", "20260721_veth9G_sp_uniform", 9),
        ("C2 (実機)\n(C=9G)", "20260721_c2_sp_uniform", 9),
    ],
}

_SUM_RE = re.compile(r"([\d.]+)\s*([KMG]?)bits/sec.*?\(([\d.]+)%\)\s+receiver")

def parse_iperf(folder, cls):
    """iperf3 receiver SUM行から (スループットGbps, 損失率%) を返す"""
    log = DATA_DIR / folder / "frr_normal" / f"iperf3_{cls}.log"
    for line in log.read_text().splitlines():
        if "SUM" in line and "receiver" in line:
            m = _SUM_RE.search(line)
            if m:
                val, unit, loss = float(m.group(1)), m.group(2), float(m.group(3))
                gbps = {"G": val, "M": val/1e3, "K": val/1e6, "": val/1e9}[unit]
                return gbps, loss
    raise RuntimeError(f"パース失敗: {log}")

_OWD_RE = re.compile(r"owd=([\d.]+)")
_OWD_TS_RE = re.compile(r"\[([\d.]+)\]\s+seq=\d+\s+owd=([\d.]+)")

def parse_owd_series(folder, cls, scenario="frr_normal"):
    """OWDログから (経過秒 list, OWD[ms] list) を返す。先頭タイムスタンプ基準で相対時刻化"""
    log = DATA_DIR / folder / scenario / f"owd_{cls}.log"
    ts, ms = [], []
    for line in log.read_text().splitlines():
        m = _OWD_TS_RE.search(line)
        if m:
            ts.append(float(m.group(1)))
            ms.append(float(m.group(2)))
    if not ts:
        raise RuntimeError(f"OWDパース失敗: {log}")
    t0 = ts[0]
    return [t - t0 for t in ts], ms

def parse_owd_binned(folder, cls, scenario="frr_normal", span=60):
    """OWDを1秒ごとの中央値に集計。受信パケットが無い秒はNaN(線の切れ目)。
    障害中(パケット全ドロップ)が欠測=切れ目として表示され、誤接続線を防ぐ。"""
    import math
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
            ys.append(math.nan)
    return xs, ys

def parse_throughput_series(folder, rx_idx, scenario="frr_normal"):
    """throughput.csv から (時刻list[s], スループットlist[Gbps]) を返す。rx_idx: 1=AF41,2=AF42,3=AF43"""
    csv = DATA_DIR / folder / scenario / "throughput.csv"
    t, gbps = [], []
    for line in csv.read_text().splitlines()[1:]:  # ヘッダ除く
        parts = line.split(",")
        if len(parts) >= 4:
            t.append(float(parts[0]))
            gbps.append(float(parts[rx_idx]) * 8 / 1e9)  # bytes/s → Gbps
    return t, gbps

# ── データ収集 ─────────────────────────────────────────────────────────
data = {}  # data[mode][cls] = [(label, gbps, loss), ...]
for mode in ("sp", "uniform"):
    data[mode] = {c: [] for c in ("af41", "af42", "af43")}
    for label, folder, cr in CONDITIONS[mode]:
        for cls in ("af41", "af42", "af43"):
            gbps, loss = parse_iperf(folder, cls)
            data[mode][cls].append((label, gbps, loss))

labels = [c[0] for c in CONDITIONS["sp"]]
x = np.arange(len(labels))
w = 0.38

C_SP      = "#2c7fb8"   # SP有効: 青
C_UNIFORM = "#d95f0e"   # SP無効: 橙

# ══ 主図: AF41 損失率 (対数軸グループ化棒) ═══════════════════════════════
fig, ax = plt.subplots(figsize=(5.2, 3.6))
sp_loss   = [max(v[2], 1e-4) for v in data["sp"]["af41"]]       # 0対策で下限
uni_loss  = [max(v[2], 1e-4) for v in data["uniform"]["af41"]]

b1 = ax.bar(x - w/2, sp_loss,  w, label="SP有効 (AF41=Strict Priority)",
            color=C_SP, edgecolor="black", linewidth=0.5)
b2 = ax.bar(x + w/2, uni_loss, w, label="SP無効 (全クラス同一prio=WRRのみ)",
            color=C_UNIFORM, edgecolor="black", linewidth=0.5)

ax.set_yscale("log")
ax.set_ylim(1e-3, 200)
ax.set_ylabel("AF41 (高優先) パケット損失率 [%]")
ax.set_xticks(x)
ax.set_xticklabels(labels)
ax.set_title("AF41 損失率: Strict Priority の有無による比較 (normalシナリオ)")
ax.grid(axis="y", which="both")
# 凡例は棒ラベルとの重なりを避けて図の下に配置
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=2,
          columnspacing=1.0, handlelength=1.5)

for bars, vals in ((b1, [v[2] for v in data["sp"]["af41"]]),
                   (b2, [v[2] for v in data["uniform"]["af41"]])):
    for rect, val in zip(bars, vals):
        txt = f"{val:.4f}%" if val < 1 else f"{val:.0f}%"
        ax.annotate(txt, (rect.get_x()+rect.get_width()/2, rect.get_height()),
                    ha="center", va="bottom", fontsize=7.5,
                    xytext=(0, 2), textcoords="offset points")

fig.tight_layout()
fig.savefig(OUT_DIR / "fig_af41_loss_ablation.png")
fig.savefig(OUT_DIR / "fig_af41_loss_ablation.pdf")
plt.close(fig)
print("[*] fig_af41_loss_ablation.png / .pdf")

# ══ 補助図: クラス別スループット (SP有効/無効の2パネル) ═══════════════════
fig, axes = plt.subplots(1, 2, figsize=(9.0, 3.6), sharey=True)
cls_names = ["AF41 (高)", "AF42 (中)", "AF43 (低)"]
cls_colors = ["#4CAE4C", "#f0ad4e", "#5bc0de"]
cw = 0.26

for ax, mode, title in ((axes[0], "sp", "SP有効 (Strict Priority + WRR)"),
                        (axes[1], "uniform", "SP無効 (WRR quantum比 4:2:1 のみ)")):
    for i, cls in enumerate(("af41", "af42", "af43")):
        vals = [v[1] for v in data[mode][cls]]
        ax.bar(x + (i-1)*cw, vals, cw, label=cls_names[i],
               color=cls_colors[i], edgecolor="black", linewidth=0.5)
        for xi, val in zip(x + (i-1)*cw, vals):
            ax.annotate(f"{val:.2f}", (xi, val), ha="center", va="bottom",
                        fontsize=6.5, xytext=(0, 1.5), textcoords="offset points")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_title(title)
    ax.grid(axis="y")
    ax.set_xlabel("実験環境")

axes[0].set_ylabel("受信スループット [Gbps]")
# 棒(と注記)の上に余白を作る。sharey なので両パネルの最大値で決める
_bar_ymax = max(v[1] for m in ("sp", "uniform") for c in ("af41", "af42", "af43")
                for v in data[m][c])
axes[0].set_ylim(0, _bar_ymax * 1.15)
# 凡例は棒に重ならない右パネル上部の空きスペースに配置
axes[1].legend(loc="upper right", title="トラフィッククラス")
fig.suptitle("クラス別受信スループット: SPの有無による帯域分配の違い", fontsize=11)
fig.tight_layout()
fig.savefig(OUT_DIR / "fig_class_throughput_ablation.png")
fig.savefig(OUT_DIR / "fig_class_throughput_ablation.pdf")
plt.close(fig)
print("[*] fig_class_throughput_ablation.png / .pdf")

# ══ 第3図: OWD (片道遅延) 60秒時系列 veth vs C2 (クラス別3段パネル) ═══════
# sim-to-realギャップの可視化: スループット/損失はソフトウェア(HTB)が決めるため
# 環境非依存で一致するが、遅延は物理層の伝搬・処理時間が乗るため実機(C2)で増える。
# AF41(優先クラス、キュー待ちほぼ無し)でのみ物理差が顕在化し、AF42/AF43は
# HTBキュー待ち時間(数百ms)が支配的で物理差が埋もれる。
cls_keys = ("af41", "af42", "af43")
cls_labels = ["AF41 (高優先)", "AF42 (中優先)", "AF43 (低優先)"]
env_colors = ["#7570b3", "#1b9e77"]
rx_map = {"af41": 1, "af42": 2, "af43": 3}

# 理論値(C=9G):
#  SP有効 = AF41が需要8Gを先取り、Yellow残余(C-8=1G)をAF42:AF43=2:1で分配
#  SP無効 = quantumフルシェア 4/7・2/7・1/7 × C（Strict Priorityが無いため）
_yellow = 9.0 - 8.0
THEORY = {
    "sp":      {"af41": 8.0, "af42": _yellow*2/3, "af43": _yellow*1/3},
    "uniform": {"af41": 4/7*9, "af42": 2/7*9, "af43": 1/7*9},
}
MODE_JP = {"sp": "SP有効", "uniform": "SP無効(prio統一)"}

def env_names_for(mode):
    return [c[0].replace("\n", " ") for c in CONDITIONS[mode]]

def plot_owd_timeseries(mode):
    """OWD 60秒時系列 (クラス別3段パネル, veth vs C2)"""
    enames = env_names_for(mode)
    fig, axes = plt.subplots(3, 1, figsize=(6.4, 6.4), sharex=True)
    for ax, cls, clab in zip(axes, cls_keys, cls_labels):
        for env_idx, (ename, ecol) in enumerate(zip(enames, env_colors)):
            folder = CONDITIONS[mode][env_idx][1]
            t, ms = parse_owd_series(folder, cls)
            ax.plot(t, ms, color=ecol, linewidth=0.9, label=ename)
        ax.set_ylabel("OWD [ms]")
        ax.set_title(clab, loc="left", fontsize=9)
        ax.set_xlim(0, 60)
        ax.grid(axis="both")
        headroom_linear(ax, bottom=0)
    axes[0].legend(loc="upper right", title="実験環境", ncol=2)
    axes[-1].set_xlabel("経過時間 [s]")
    fig.suptitle(f"片道遅延の時系列: シミュレーション(veth) vs 実機(C2)  "
                 f"({MODE_JP[mode]}・normal)", fontsize=11)
    fig.tight_layout()
    stem = "fig_owd_timeseries" + ("" if mode == "sp" else "_uniform")
    # SP有効版は従来ファイル名(fig_owd_sim_vs_real)を維持
    if mode == "sp":
        stem = "fig_owd_sim_vs_real"
    fig.savefig(OUT_DIR / f"{stem}.png")
    fig.savefig(OUT_DIR / f"{stem}.pdf")
    plt.close(fig)
    print(f"[*] {stem}.png / .pdf")

# シナリオ定義: (フォルダ名, 日本語ラベル, ファイル名サフィックス, 障害区間の網掛け有無)
SCENARIOS = {
    "normal":          ("frr_normal", "normal", "", False),
    "failure":         ("frr_failure", "failure(迂回なし)", "_failure", True),
    "failure_reroute": ("frr_failure_reroute", "failure_reroute(自動迂回)", "_reroute", True),
}
FAILURE_WINDOW = (20, 40)   # CLAUDE.md: t=20s CR1ダウン → t=40s復旧

def plot_throughput_timeseries(mode, scenario="normal"):
    """スループット 60秒時系列 (クラス別3段パネル, veth vs C2, 理論値破線)"""
    sc_folder, sc_jp, sc_sfx, shade = SCENARIOS[scenario]
    enames = env_names_for(mode)
    fig, axes = plt.subplots(3, 1, figsize=(6.4, 6.4), sharex=True)
    for ax, cls, clab in zip(axes, cls_keys, cls_labels):
        if shade:
            ax.axvspan(*FAILURE_WINDOW, color="#d95f0e", alpha=0.08,
                       label="障害区間 (t=20–40s)")
        for env_idx, (ename, ecol) in enumerate(zip(enames, env_colors)):
            folder = CONDITIONS[mode][env_idx][1]
            t, g = parse_throughput_series(folder, rx_map[cls], sc_folder)
            ax.plot(t, g, color=ecol, linewidth=1.0, label=ename)
        ax.axhline(THEORY[mode][cls], color="0.4", linestyle=":", linewidth=1.0,
                   label=f"理論値 {THEORY[mode][cls]:.2f} Gbps")
        ax.set_ylabel("スループット [Gbps]")
        ax.set_title(clab, loc="left", fontsize=9)
        ax.set_xlim(0, 60)
        ax.grid(axis="both")
        headroom_linear(ax, bottom=0)
    axes[0].legend(loc="center right", fontsize=8, ncol=1)
    axes[-1].set_xlabel("経過時間 [s]")
    fig.suptitle(f"受信スループットの時系列: シミュレーション(veth) vs 実機(C2)  "
                 f"({MODE_JP[mode]}・{sc_jp})", fontsize=11)
    fig.tight_layout()
    stem = "fig_throughput_timeseries" + ("" if mode == "sp" else "_uniform") + sc_sfx
    fig.savefig(OUT_DIR / f"{stem}.png")
    fig.savefig(OUT_DIR / f"{stem}.pdf")
    plt.close(fig)
    print(f"[*] {stem}.png / .pdf")

# 既存 plot_frr.py と統一したシナリオ配色 (キー, 凡例ラベル, 色, 線種)
SC_STYLE = [
    ("normal",          "正常時",           "#4CAE4C", "-"),
    ("failure",         "障害(迂回なし)",    "#DC4748", "--"),
    ("failure_reroute", "障害(自動迂回)",    "#418BBF", "-."),
]

def plot_scenario_comparison(mode, env_idx=1):
    """1枚に3シナリオ(normal/failure/reroute)を重ねたスループット時系列。
    env_idx=1(C2実機)を代表として使用(veth≈C2は別図で確認済み)。"""
    folder = CONDITIONS[mode][env_idx][1]
    env_label = env_names_for(mode)[env_idx]
    sc_style = SC_STYLE
    fig, axes = plt.subplots(3, 1, figsize=(6.6, 6.6), sharex=True)
    for ax, cls, clab in zip(axes, cls_keys, cls_labels):
        ax.axvspan(*FAILURE_WINDOW, color="#d95f0e", alpha=0.07)
        for sc_key, sc_lab, scol, sls in sc_style:
            sc_folder = SCENARIOS[sc_key][0]
            t, g = parse_throughput_series(folder, rx_map[cls], sc_folder)
            ax.plot(t, g, color=scol, linestyle=sls, linewidth=1.3, label=sc_lab)
        ax.axhline(THEORY[mode][cls], color="0.5", linestyle=":", linewidth=0.9)
        ax.set_ylabel("スループット [Gbps]")
        ax.set_title(clab, loc="left", fontsize=9)
        ax.set_xlim(0, 60)
        ax.grid(axis="both")
        headroom_linear(ax, bottom=0)
    axes[0].legend(loc="center right", fontsize=8, ncol=1)
    axes[-1].set_xlabel("経過時間 [s]")
    fig.suptitle(f"シナリオ別 受信スループット時系列 ({env_label}, {MODE_JP[mode]})\n"
                 f"障害区間 t=20–40s を網掛け", fontsize=11)
    fig.tight_layout()
    stem = "fig_scenario_comparison" + ("" if mode == "sp" else "_uniform")
    fig.savefig(OUT_DIR / f"{stem}.png")
    fig.savefig(OUT_DIR / f"{stem}.pdf")
    plt.close(fig)
    print(f"[*] {stem}.png / .pdf")

def plot_scenario_comparison_combined(env_idx=1):
    """SP有効(左列)とSP無効(右列)を1枚に合体。行=クラス, 各セルに3シナリオを重ねる。
    fig_scenario_comparison{,_uniform}.png を左右に並べた統合版。"""
    folder_of = {m: CONDITIONS[m][env_idx][1] for m in ("sp", "uniform")}
    env_label = env_names_for("sp")[env_idx]
    modes = ["sp", "uniform"]
    # y軸スケールはSP有効/無効で理論値が異なるため列ごとに独立(sharey しない)
    fig, axes = plt.subplots(3, 2, figsize=(11.0, 7.0), sharex=True)
    for row, (cls, clab) in enumerate(zip(cls_keys, cls_labels)):
        for col, mode in enumerate(modes):
            ax = axes[row][col]
            ax.axvspan(*FAILURE_WINDOW, color="#d95f0e", alpha=0.07)
            for sc_key, sc_lab, scol, sls in SC_STYLE:
                t, g = parse_throughput_series(folder_of[mode], rx_map[cls],
                                               SCENARIOS[sc_key][0])
                ax.plot(t, g, color=scol, linestyle=sls, linewidth=1.2, label=sc_lab)
            ax.axhline(THEORY[mode][cls], color="0.5", linestyle=":", linewidth=0.9)
            ax.set_xlim(0, 60)
            ax.grid(axis="both")
            headroom_linear(ax, bottom=0)
            if row == 0:
                ax.set_title(MODE_JP[mode], fontsize=11, pad=6)
            if col == 0:
                ax.set_ylabel(f"{clab}\nスループット [Gbps]")
    for col in range(2):
        axes[-1][col].set_xlabel("経過時間 [s]")
    axes[0][1].legend(loc="upper right", fontsize=8, ncol=1)
    fig.suptitle(f"シナリオ別 受信スループット時系列 — SP有効 vs SP無効 の統合比較 "
                 f"({env_label}, 障害区間 t=20–40s 網掛け)", fontsize=12)
    fig.tight_layout()
    stem = "fig_scenario_comparison_combined"
    fig.savefig(OUT_DIR / f"{stem}.png")
    fig.savefig(OUT_DIR / f"{stem}.pdf")
    plt.close(fig)
    print(f"[*] {stem}.png / .pdf")

def plot_owd_comparison_combined(env_idx=1):
    """遅延(OWD)版の左右分割図。行=クラス, 列=SP有効/無効, 各セルに3シナリオを重ねる。
    fig_scenario_comparison_combined(スループット)の遅延版。各セル単一モードで値域が
    狭いため線形軸(通常の目盛)を使用し読みやすくする。1秒中央値。"""
    folder_of = {m: CONDITIONS[m][env_idx][1] for m in ("sp", "uniform")}
    env_label = env_names_for("sp")[env_idx]
    modes = ["sp", "uniform"]
    fig, axes = plt.subplots(3, 2, figsize=(11.0, 7.0), sharex=True)
    for row, (cls, clab) in enumerate(zip(cls_keys, cls_labels)):
        for col, mode in enumerate(modes):
            ax = axes[row][col]
            ax.axvspan(*FAILURE_WINDOW, color="#d95f0e", alpha=0.07)
            for sc_key, sc_lab, scol, sls in SC_STYLE:
                x, y = parse_owd_binned(folder_of[mode], cls, SCENARIOS[sc_key][0])
                ax.plot(x, y, color=scol, linestyle=sls, linewidth=1.2, label=sc_lab)
            ax.set_xlim(0, 60)
            ax.grid(axis="both")
            headroom_linear(ax, bottom=0)
            if row == 0:
                ax.set_title(MODE_JP[mode], fontsize=11, pad=6)
            if col == 0:
                ax.set_ylabel(f"{clab}\nOWD [ms]")
    for col in range(2):
        axes[-1][col].set_xlabel("経過時間 [s]")
    axes[0][1].legend(loc="upper right", fontsize=8, ncol=1)
    fig.suptitle(f"シナリオ別 片道遅延OWD時系列 — SP有効 vs SP無効 の統合比較 "
                 f"({env_label}, 障害区間 t=20–40s 網掛け, 1秒中央値)", fontsize=12)
    fig.tight_layout()
    stem = "fig_owd_comparison_combined"
    fig.savefig(OUT_DIR / f"{stem}.png")
    fig.savefig(OUT_DIR / f"{stem}.pdf")
    plt.close(fig)
    print(f"[*] {stem}.png / .pdf")

def plot_scenario_comparison_shared(env_idx=1):
    """SP有効とSP無効を『同じ軸に重ねて』比較。行=クラス(3段, 各パネル共有軸)。
    色=シナリオ(正常/迂回なし/自動迂回)、線種=SPモード(有効=実線/無効=破線)。
    左右分割(combined版)と異なり、SP有無の絶対値差(例: AF41 8G vs 5.3G)が
    同一スケール上で直接読める。"""
    from matplotlib.lines import Line2D
    folder_of = {m: CONDITIONS[m][env_idx][1] for m in ("sp", "uniform")}
    env_label = env_names_for("sp")[env_idx]
    sc_color = {k: c for (k, lab, c, ls) in SC_STYLE}
    sc_jp    = {k: lab for (k, lab, c, ls) in SC_STYLE}
    mode_ls  = {"sp": "-", "uniform": "--"}

    fig, axes = plt.subplots(3, 1, figsize=(7.2, 7.4), sharex=True)
    for ax, cls, clab in zip(axes, cls_keys, cls_labels):
        ax.axvspan(*FAILURE_WINDOW, color="#d95f0e", alpha=0.07)
        for mode in ("sp", "uniform"):
            for sc_key in ("normal", "failure", "failure_reroute"):
                t, g = parse_throughput_series(folder_of[mode], rx_map[cls],
                                               SCENARIOS[sc_key][0])
                ax.plot(t, g, color=sc_color[sc_key], linestyle=mode_ls[mode],
                        linewidth=1.2)
        ax.set_ylabel("スループット [Gbps]")
        ax.set_title(clab, loc="left", fontsize=9)
        ax.set_xlim(0, 60)
        ax.grid(axis="both")
        headroom_linear(ax, bottom=0)
    axes[-1].set_xlabel("経過時間 [s]")

    # 2種類の凡例: 色=シナリオ, 線種=SPモード
    color_handles = [Line2D([0], [0], color=sc_color[k], lw=2, label=sc_jp[k])
                     for k in ("normal", "failure", "failure_reroute")]
    style_handles = [Line2D([0], [0], color="0.3", lw=1.5, linestyle="-",  label="SP有効"),
                     Line2D([0], [0], color="0.3", lw=1.5, linestyle="--", label="SP無効")]
    leg1 = axes[0].legend(handles=color_handles, loc="upper right",
                          fontsize=8, title="シナリオ(色)")
    axes[0].add_artist(leg1)
    axes[0].legend(handles=style_handles, loc="lower right",
                   fontsize=8, title="SPモード(線種)")

    fig.suptitle(f"受信スループット時系列 — SP有効/無効 を同一軸で重ねた比較\n"
                 f"({env_label}, 障害区間 t=20–40s 網掛け)", fontsize=11)
    fig.tight_layout()
    stem = "fig_scenario_comparison_shared"
    fig.savefig(OUT_DIR / f"{stem}.png")
    fig.savefig(OUT_DIR / f"{stem}.pdf")
    plt.close(fig)
    print(f"[*] {stem}.png / .pdf")

def plot_owd_comparison_shared(env_idx=1):
    """遅延(OWD)版の同一軸重ね比較。行=クラス(3段, 対数軸)。
    色=シナリオ, 線種=SPモード。SP有効/無効でOWDが桁違い(AF41: 0.16ms vs 13.7ms)
    のため対数軸。障害中は受信パケット無しで欠測=線の切れ目として表示。"""
    from matplotlib.lines import Line2D
    folder_of = {m: CONDITIONS[m][env_idx][1] for m in ("sp", "uniform")}
    env_label = env_names_for("sp")[env_idx]
    sc_color = {k: c for (k, lab, c, ls) in SC_STYLE}
    sc_jp    = {k: lab for (k, lab, c, ls) in SC_STYLE}
    mode_ls  = {"sp": "-", "uniform": "--"}

    fig, axes = plt.subplots(3, 1, figsize=(7.2, 7.4), sharex=True)
    for ax, cls, clab in zip(axes, cls_keys, cls_labels):
        ax.axvspan(*FAILURE_WINDOW, color="#d95f0e", alpha=0.07)
        for mode in ("sp", "uniform"):
            for sc_key in ("normal", "failure", "failure_reroute"):
                x, y = parse_owd_binned(folder_of[mode], cls, SCENARIOS[sc_key][0])
                ax.plot(x, y, color=sc_color[sc_key], linestyle=mode_ls[mode],
                        linewidth=1.2)
        ax.set_yscale("log")
        ax.set_ylabel("OWD [ms]")
        ax.set_title(clab, loc="left", fontsize=9)
        ax.set_xlim(0, 60)
        ax.grid(axis="both", which="both")
        headroom_log(ax, factor=2.2)
    axes[-1].set_xlabel("経過時間 [s]")

    color_handles = [Line2D([0], [0], color=sc_color[k], lw=2, label=sc_jp[k])
                     for k in ("normal", "failure", "failure_reroute")]
    style_handles = [Line2D([0], [0], color="0.3", lw=1.5, linestyle="-",  label="SP有効"),
                     Line2D([0], [0], color="0.3", lw=1.5, linestyle="--", label="SP無効")]
    leg1 = axes[0].legend(handles=color_handles, loc="upper right",
                          fontsize=8, title="シナリオ(色)")
    axes[0].add_artist(leg1)
    axes[0].legend(handles=style_handles, loc="lower right",
                   fontsize=8, title="SPモード(線種)")

    fig.suptitle(f"片道遅延OWD時系列 — SP有効/無効 を同一軸(対数)で重ねた比較\n"
                 f"({env_label}, 障害区間 t=20–40s 網掛け, 1秒中央値)", fontsize=11)
    fig.tight_layout()
    stem = "fig_owd_comparison_shared"
    fig.savefig(OUT_DIR / f"{stem}.png")
    fig.savefig(OUT_DIR / f"{stem}.pdf")
    plt.close(fig)
    print(f"[*] {stem}.png / .pdf")

# SP有効・SP無効 × 各種時系列図を生成
# OWDはnormalのみ(sim-to-real用)、スループットは全シナリオ(障害挙動の比較用)
for _mode in ("sp", "uniform"):
    plot_owd_timeseries(_mode)                          # normal OWD
    for _sc in ("normal", "failure", "failure_reroute"):
        plot_throughput_timeseries(_mode, _sc)          # シナリオ別 veth vs C2
    plot_scenario_comparison(_mode)                     # 3シナリオ重ね (C2実機、モード別)
plot_scenario_comparison_combined()                     # スループット SP有効/無効 左右分割版
plot_scenario_comparison_shared()                       # スループット SP有効/無効 同一軸重ね版
plot_owd_comparison_combined()                          # 遅延OWD SP有効/無効 左右分割版
plot_owd_comparison_shared()                            # 遅延OWD SP有効/無効 同一軸重ね版

# ── 数値サマリを標準出力 ───────────────────────────────────────────────
print("\n=== AF41損失率 (実データ算出値) ===")
for mode in ("sp", "uniform"):
    print(f"  [{mode}]", ", ".join(
        f"{lbl.splitlines()[0]}={loss:.4f}%"
        for (lbl, g, loss) in data[mode]["af41"]))
