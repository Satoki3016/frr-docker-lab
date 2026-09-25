#!/usr/bin/env python3
"""
plot_packet_flow.py — 実験の実装構成とパケットの流れを示す図

Testbed スライドの次に置く。論理トポロジ（Tx→ルータ→Rx）が実際には
どう実装されているか、パケットが各段で何をされるかを1枚で示す。

事実の出典:
  - コンテナ構成      scripts/frr_setup.sh:51,71  (Docker 11コンテナ)
  - veth 区間         scripts/frr_setup.sh:183-189, 217-219
  - 物理区間 (C2)     scripts/frr_setup.sh:149-150, 164-180
                      CR1/2/3 と LER_Egress に専用の物理NICペアを割り当て
  - VLAN 201-203      scripts/lab_config_c2.sh
  - 送信条件          scripts/lab_config_c2.sh (2G×4=8G/クラス)
  - DSCP/HTB/MPLS     scripts/frr_dscp_te.sh
  - プローブ          scripts/owd_sender.py (--interval 0.02)

見た目の調整:
  FONT / COLOR / LAYOUT の3辞書のみを編集すればよい。

使い方:
    python3 plot_packet_flow.py [--lang en|ja] [--outdir DIR]
"""
import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

BASE = Path(__file__).resolve().parent.parent
OUT_TAG = "qos/c2/20260721_c2_sp_enabled"

FONT = {
    "box_title": 15,   # 箱の中の名前（Tx1 / LER_Ingress など）
    "box_body":  11,   # 箱の下の処理内容
    "link":       10,  # 矢印に添える区間の種別（箱の間隔に収まる大きさにする）
    "legend":     12,  # 下部の凡例
    "note":       11,  # 障害注入位置の注記
}

COLOR = {
    "container":   "#DCE6F2",   # コンテナの箱（塗り）
    "container_e": "#12307E",   # コンテナの箱（枠・文字）
    "physical":    "#EDEDED",   # 物理スイッチの箱（塗り）
    "physical_e":  "#555555",   # 物理スイッチの箱（枠・文字）
    "arrow_veth":  "#8A8A8A",   # veth 区間の矢印
    "arrow_phys":  "#12307E",   # 物理区間の矢印（太く濃く）
    "body":        "#333333",   # 処理内容の文字
    "fault":       "#DC4748",   # 障害注入の注記
}

# 座標系は x:0-100, y:0-100。1データ単位 = width/100 インチ。
# 箱の幅は「最長のタイトルが収まる幅」から決めている（LER_Ingress が最長）。
LAYOUT = {
    "width":       15.0,   # 図の幅 [inch]
    "height":       4.2,   # 図の高さ [inch]
    "box_w":       11.0,   # 箱の幅
    "box_h":       13.0,   # 箱の高さ
    "box_y":       58.0,   # 箱の下端
    "x_first":      7.0,   # 左端の箱の中心
    "x_last":      93.0,   # 右端の箱の中心
    "gap":          0.8,   # 箱と矢印の隙間
    "arrow_w_veth": 2.0,   # veth 矢印の線幅
    "arrow_w_phys": 3.6,   # 物理矢印の線幅
    "body_dy":      4.0,   # 箱の下端から処理内容までの距離
    "link_dy":      2.6,   # 矢印から種別ラベルまでの距離
    "ylim_lo":     16.0,   # 縦方向の表示範囲。描画内容に合わせて余白を詰める
    "ylim_hi":     86.0,
}

# (種別, タイトルキー, 本文キー)。x座標は x_first〜x_last に等間隔で配置する。
STAGES = [
    ("container", "tx",   "tx_body"),
    ("container", "leri", "leri_body"),
    ("container", "cr",   "cr_body"),
    ("physical",  "sw",   "sw_body"),
    ("container", "lere", "lere_body"),
    ("container", "rx",   "rx_body"),
]


def stage_x(i: int) -> float:
    """i番目の段の中心x座標。"""
    n = len(STAGES)
    step = (LAYOUT["x_last"] - LAYOUT["x_first"]) / (n - 1)
    return LAYOUT["x_first"] + step * i

# (左の段index, 右の段index, 区間の種別)
LINKS = [(0, 1, "veth"), (1, 2, "veth"), (2, 3, "phys"), (3, 4, "phys"), (4, 5, "veth")]

_TXT = {
    "en": {
        "tx": "Tx1-3",
        "tx_body": "iperf3 UDP, 8 Gbps each\nDSCP 34 / 36 / 38\n+ probes every 20 ms",
        "leri": "LER_Ingress",
        "leri_body": "classify by DSCP\nHTB: SP + WRR\npush MPLS label",
        "cr": "CR1-3",
        "cr_body": "MPLS label switch\nHTB per class",
        "sw": "SW1→SW2",
        "sw_body": "one dedicated cable\nper path",
        "lere": "LER_Egress",
        "lere_body": "pop MPLS label",
        "rx": "Rx1-3",
        "rx_body": "iperf3 server\nprobe receiver\n→ CSV logs",
        "veth": "veth",
        "phys": "10 GbE×3",
        "leg_container": "Docker container (all on one Linux host)",
        "leg_physical": "physical switch",
        "fault": "failure injected here\n(Router 1 link, t = 20 s)",
    },
    "ja": {
        "tx": "Tx1-3",
        "tx_body": "iperf3 UDP 各8 Gbps\nDSCP 34 / 36 / 38\n+ 20 ms間隔プローブ",
        "leri": "LER_Ingress",
        "leri_body": "DSCPで分類\nHTB: SP + WRR\nMPLSラベル付与",
        "cr": "CR1-3",
        "cr_body": "MPLSラベル転送\nクラス別HTB",
        "sw": "SW1→SW2",
        "sw_body": "経路ごとに専用ケーブル",
        "lere": "LER_Egress",
        "lere_body": "MPLSラベル除去",
        "rx": "Rx1-3",
        "rx_body": "iperf3 サーバ\nプローブ受信\n→ CSV",
        "veth": "veth",
        "phys": "物理10G×3",
        "leg_container": "Dockerコンテナ（すべて同一Linux上）",
        "leg_physical": "物理スイッチ",
        "fault": "障害注入箇所\n(Router 1 のリンク, t = 20 s)",
    },
}


def setup_font(lang: str):
    if lang == "en":
        matplotlib.rcParams["font.family"] = "DejaVu Sans"
    else:
        import matplotlib.font_manager as fm
        for f in ["Noto Sans CJK JP", "TakaoPGothic", "IPAPGothic", "VL PGothic"]:
            if any(f.lower() in p.name.lower() for p in fm.fontManager.ttflist):
                matplotlib.rcParams["font.family"] = f
                break
    matplotlib.rcParams["figure.facecolor"] = "white"


def draw_box(ax, xc, kind, title, body):
    fill = COLOR["container"] if kind == "container" else COLOR["physical"]
    edge = COLOR["container_e"] if kind == "container" else COLOR["physical_e"]
    w, h, y = LAYOUT["box_w"], LAYOUT["box_h"], LAYOUT["box_y"]
    ax.add_patch(FancyBboxPatch(
        (xc - w / 2, y), w, h,
        boxstyle="round,pad=0.6,rounding_size=1.2",
        linewidth=1.8, facecolor=fill, edgecolor=edge, zorder=3))
    ax.text(xc, y + h / 2, title, ha="center", va="center",
            fontsize=FONT["box_title"], fontweight="bold", color=edge, zorder=4)
    ax.text(xc, y - LAYOUT["body_dy"], body, ha="center", va="top",
            fontsize=FONT["box_body"], color=COLOR["body"], linespacing=1.5, zorder=4)


def draw_link(ax, x_from, x_to, kind, label):
    """箱と箱のあいだに矢印を引き、区間の種別を上に添える。"""
    half, gap = LAYOUT["box_w"] / 2, LAYOUT["gap"]
    x0, x1 = x_from + half + gap, x_to - half - gap
    y = LAYOUT["box_y"] + LAYOUT["box_h"] / 2
    color = COLOR["arrow_veth"] if kind == "veth" else COLOR["arrow_phys"]
    lw = LAYOUT["arrow_w_veth"] if kind == "veth" else LAYOUT["arrow_w_phys"]
    ax.add_patch(FancyArrowPatch(
        (x0, y), (x1, y), arrowstyle="-|>", mutation_scale=18,
        linewidth=lw, color=color, zorder=2))
    ax.text((x0 + x1) / 2, y + LAYOUT["link_dy"], label, ha="center", va="bottom",
            fontsize=FONT["link"], color=color, zorder=4)


def build(lang: str):
    T = _TXT[lang]
    setup_font(lang)

    fig, ax = plt.subplots(figsize=(LAYOUT["width"], LAYOUT["height"]))
    ax.set_xlim(0, 104)
    ax.set_ylim(LAYOUT["ylim_lo"], LAYOUT["ylim_hi"])
    ax.axis("off")

    for i, (kind, tk, bk) in enumerate(STAGES):
        draw_box(ax, stage_x(i), kind, T[tk], T[bk])

    for i, j, kind in LINKS:
        draw_link(ax, stage_x(i), stage_x(j), kind, T[kind])

    # 障害注入位置（LER_Ingress → CR 区間）を赤で注記する
    x_mid = (stage_x(1) + stage_x(2)) / 2
    ax.annotate(T["fault"],
                xy=(x_mid, LAYOUT["box_y"] + LAYOUT["box_h"] / 2 - 1.5),
                xytext=(x_mid, LAYOUT["box_y"] - 26),
                ha="center", va="top", fontsize=FONT["note"], color=COLOR["fault"],
                linespacing=1.4,
                arrowprops=dict(arrowstyle="->", color=COLOR["fault"], lw=1.6))

    handles = [
        plt.Rectangle((0, 0), 1, 1, facecolor=COLOR["container"],
                      edgecolor=COLOR["container_e"], linewidth=1.5),
        plt.Rectangle((0, 0), 1, 1, facecolor=COLOR["physical"],
                      edgecolor=COLOR["physical_e"], linewidth=1.5),
    ]
    ax.legend(handles, [T["leg_container"], T["leg_physical"]],
              loc="upper center", bbox_to_anchor=(0.5, 1.02), ncol=2,
              frameon=False, fontsize=FONT["legend"])

    outdir = BASE / OUT_TAG / lang
    outdir.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf"):
        p = outdir / f"packet_flow.{ext}"
        fig.savefig(p, dpi=300, bbox_inches="tight")
        print(f"[*] {p}")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="both", choices=("en", "ja", "both"))
    args = ap.parse_args()
    for lang in (("en", "ja") if args.lang == "both" else (args.lang,)):
        build(lang)


if __name__ == "__main__":
    main()
