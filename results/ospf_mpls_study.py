#!/usr/bin/env python3
"""
OSPF + MPLS + Segment Routing  自習用PDF生成スクリプト
研究で使用している技術を1から理解するためのドキュメント
実行: python3 results/ospf_mpls_study.py
出力: results/ospf_mpls_study.pdf
"""

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patches as mpatches
from matplotlib.backends.backend_pdf import PdfPages
from pathlib import Path
import textwrap

# ── フォント ──────────────────────────────────────────────────────────────
for _f in ["Noto Sans CJK JP", "TakaoPGothic", "IPAPGothic", "VL PGothic"]:
    if any(_f.lower() in p.name.lower() for p in fm.fontManager.ttflist):
        matplotlib.rcParams["font.family"] = _f
        break
matplotlib.rcParams.update({"figure.facecolor": "white"})

OUT = Path(__file__).parent / "ospf_mpls_study.pdf"

# ── カラーパレット ────────────────────────────────────────────────────────
CB  = "#1565C0"   # blue (OSPF)
CG  = "#2E7D32"   # green (MPLS)
CO  = "#E65100"   # orange (SR)
CR  = "#B71C1C"   # red (failure)
CGR = "#424242"   # dark gray (body)
CL  = "#E8F4FD"   # light blue bg
CGL = "#F1F8E9"   # light green bg
COL = "#FFF3E0"   # light orange bg
CW  = "white"

# ── ページ生成ヘルパー ────────────────────────────────────────────────────
def new_page(header=None, chapter=None):
    """A4縦 (8.27×11.69in) ページを作成。header がある場合は上部帯を描く。"""
    fig = plt.figure(figsize=(8.27, 11.69), facecolor="white")
    if header:
        hax = fig.add_axes([0, 0.947, 1, 0.053])
        hax.set_facecolor(CB)
        hax.set_axis_off()
        hax.text(0.03, 0.5, header, color=CW, fontsize=11.5,
                 fontweight="bold", va="center")
        if chapter:
            hax.text(0.97, 0.5, chapter, color="#90CAF9", fontsize=9,
                     va="center", ha="right")
        ax = fig.add_axes([0.07, 0.025, 0.86, 0.91])
    else:
        ax = fig.add_axes([0.05, 0.02, 0.90, 0.96])
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    return fig, ax

def T(ax, x, y, s, sz=9.5, c=CGR, bold=False, ha="left", va="top", alpha=1.0):
    ax.text(x, y, s, fontsize=sz, color=c, fontweight="bold" if bold else "normal",
            ha=ha, va=va, transform=ax.transAxes, alpha=alpha,
            multialignment="left")

def section(ax, y, text, color=CB, indent=0):
    """セクション見出し。y座標を返す（次のコンテンツ開始位置）。"""
    ax.plot([indent, 1], [y + 0.003, y + 0.003], color=color, lw=1.2,
            alpha=0.4, transform=ax.transAxes)
    ax.text(indent, y, f"▌ {text}", fontsize=11, color=color,
            fontweight="bold", va="top", transform=ax.transAxes)
    return y - 0.042

def bullet(ax, x, y, items, sz=9.2, c=CGR, gap=0.028, marker="●"):
    """箇条書きリスト。最後のy座標を返す。"""
    for item in items:
        ax.text(x, y, marker, fontsize=sz, color=CB, va="top",
                transform=ax.transAxes)
        ax.text(x + 0.035, y, item, fontsize=sz, color=c, va="top",
                transform=ax.transAxes, multialignment="left")
        y -= gap
    return y

def rect_node(ax, x, y, w, h, label, sublabel=None,
              fc=CL, ec=CB, tc=CB, sz=9, bold=True):
    """角丸ボックス"""
    r = mpatches.FancyBboxPatch((x, y), w, h,
                                 boxstyle="round,pad=0.01",
                                 facecolor=fc, edgecolor=ec, linewidth=1.8,
                                 transform=ax.transAxes, zorder=2)
    ax.add_patch(r)
    ty = y + h/2 + (0.01 if sublabel else 0)
    ax.text(x + w/2, ty, label, fontsize=sz, color=tc, ha="center", va="center",
            fontweight="bold" if bold else "normal",
            transform=ax.transAxes, zorder=3)
    if sublabel:
        ax.text(x + w/2, y + h/2 - 0.018, sublabel, fontsize=7.5, color=CGR,
                ha="center", va="center", transform=ax.transAxes, zorder=3)

def arr(ax, x1, y1, x2, y2, label="", color=CB, lw=1.6, style="->"):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                xycoords="axes fraction", textcoords="axes fraction",
                arrowprops=dict(arrowstyle=style, color=color, lw=lw), zorder=3)
    if label:
        mx, my = (x1+x2)/2, (y1+y2)/2
        ax.text(mx, my + 0.012, label, fontsize=7.5, color=color,
                ha="center", va="bottom", transform=ax.transAxes,
                bbox=dict(fc="white", ec="none", pad=1), zorder=4)

def callout(ax, x, y, w, h, text, fc=CGL, ec=CG, sz=9):
    r = mpatches.FancyBboxPatch((x, y), w, h,
                                 boxstyle="round,pad=0.015",
                                 facecolor=fc, edgecolor=ec, linewidth=1.5,
                                 transform=ax.transAxes, zorder=2)
    ax.add_patch(r)
    ax.text(x + 0.015, y + h - 0.018, text, fontsize=sz, color=CGR,
            va="top", transform=ax.transAxes, zorder=3,
            multialignment="left")

def hr(ax, y, color=CB, alpha=0.15):
    ax.plot([0, 1], [y, y], color=color, lw=0.8, alpha=alpha, transform=ax.transAxes)

def page_num(fig, n):
    fig.text(0.95, 0.012, f"─ {n} ─", fontsize=8, color=CGR, ha="right")

# ═══════════════════════════════════════════════════════════════════════════
# P1: タイトルページ
# ═══════════════════════════════════════════════════════════════════════════
def page_title(pdf):
    fig, ax = new_page()

    # 上部カラーブロック
    top = mpatches.Rectangle((0, 0.72), 1, 0.28, facecolor=CB,
                               transform=ax.transAxes, zorder=0)
    ax.add_patch(top)

    T(ax, 0.5, 0.96, "OSPF と MPLS", sz=30, c=CW, bold=True, ha="center")
    T(ax, 0.5, 0.87, "Segment Routing (SR-MPLS) まで", sz=17, c="#90CAF9",
      bold=False, ha="center")
    T(ax, 0.5, 0.78, "― 研究で使用している技術を 1 から理解する ―",
      sz=11, c="#B3E5FC", ha="center")

    # サブタイトル帯
    mid = mpatches.Rectangle((0.05, 0.67), 0.90, 0.038, facecolor="#E3F2FD",
                               transform=ax.transAxes, zorder=0)
    ax.add_patch(mid)
    T(ax, 0.5, 0.695, "FRR OSPF-SR + DiffServ-TE ラボ 技術解説",
      sz=11, c=CB, bold=True, ha="center", va="center")

    # 目次プレビュー
    chapters = [
        ("第 1 章", "IP ルーティング基礎       ─ なぜ動的ルーティングが必要か"),
        ("第 2 章", "OSPF の仕組み            ─ Hello / LSA / SPF / BFD"),
        ("第 3 章", "MPLS の仕組み            ─ ラベル転送 / PUSH・SWAP・POP"),
        ("第 4 章", "Segment Routing (SR)   ─ SRGB / Node SID / 単一ラベル転送"),
        ("第 5 章", "本研究ラボでの動作        ─ 転送フロー / 障害検出 / 迂回"),
    ]
    y = 0.60
    for ch, desc in chapters:
        ax.text(0.08, y, ch, fontsize=10, color=CB, fontweight="bold",
                va="top", transform=ax.transAxes)
        ax.text(0.26, y, desc, fontsize=10, color=CGR,
                va="top", transform=ax.transAxes)
        hr(ax, y - 0.012, alpha=0.1)
        y -= 0.062

    # ラボトポロジー概略図（章リスト下に配置）
    y0 = 0.13
    rect_node(ax, 0.02, y0,       0.10, 0.055, "Tx1/2/3",    fc="#FFF9C4", ec="#F9A825", tc="#E65100", sz=8)
    rect_node(ax, 0.16, y0,       0.15, 0.055, "LER\nIngress", fc=CL, ec=CB, tc=CB, sz=8)
    rect_node(ax, 0.36, y0+0.065, 0.12, 0.048, "CR1",  fc=CGL, ec=CG, tc=CG, sz=8)
    rect_node(ax, 0.36, y0+0.004, 0.12, 0.048, "CR2",  fc=CGL, ec=CG, tc=CG, sz=8)
    rect_node(ax, 0.36, y0-0.057, 0.12, 0.048, "CR3",  fc=CGL, ec=CG, tc=CG, sz=8)
    rect_node(ax, 0.53, y0,       0.15, 0.055, "LER\nEgress", fc=CL, ec=CB, tc=CB, sz=8)
    rect_node(ax, 0.73, y0,       0.10, 0.055, "Rx1/2/3",   fc="#E8F5E9", ec="#66BB6A", tc=CG, sz=8)

    arr(ax, 0.12, y0+0.027, 0.16, y0+0.027, color="#F9A825")
    arr(ax, 0.31, y0+0.027, 0.36, y0+0.089, color=CG)
    arr(ax, 0.31, y0+0.027, 0.36, y0+0.028, color=CG)
    arr(ax, 0.31, y0+0.027, 0.36, y0-0.033, color=CG)
    arr(ax, 0.48, y0+0.089, 0.53, y0+0.027, color=CG)
    arr(ax, 0.48, y0+0.028, 0.53, y0+0.027, color=CG)
    arr(ax, 0.48, y0-0.033, 0.53, y0+0.027, color=CG)
    arr(ax, 0.68, y0+0.027, 0.73, y0+0.027, color="#66BB6A")

    ax.text(0.44, y0+0.125, "OSPF-SR label 16005 / ECMP 3 経路",
            fontsize=7.5, color=CO, ha="center", va="bottom", transform=ax.transAxes)

    T(ax, 0.5, 0.03, "本資料の目的: 研究で使用している OSPF-SR / MPLS / DiffServ-TE の技術を基礎から段階的に理解する",
      sz=8.5, c=CGR, ha="center")

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

# ═══════════════════════════════════════════════════════════════════════════
# P2: 第1章 IPルーティング基礎
# ═══════════════════════════════════════════════════════════════════════════
def page_ch1(pdf):
    fig, ax = new_page("第 1 章　IP ルーティング基礎", "OSPF と MPLS を理解するための土台")
    page_num(fig, 2)
    y = 0.97

    y = section(ax, y, "1.1　パケットとは？")
    T(ax, 0.02, y,
      "インターネット上のデータはすべて「パケット」という小さな単位に分割されて送受信されます。\n"
      "各パケットには「宛先IPアドレス」が書かれた封筒のようなヘッダが付いており、\n"
      "ルータはこのヘッダを読んで次の転送先を決定します。",
      sz=9.5, c=CGR)
    y -= 0.08

    # IPヘッダ図
    fields = [("宛先IP\n192.168.0.5", 0.20), ("送信元IP\n10.10.1.1", 0.20),
              ("TTL\n64", 0.10), ("Protocol\nUDP", 0.14), ("データ\n(payload)", 0.36)]
    x = 0.02
    for fname, fw in fields:
        fc = CL if "宛先" in fname else "#F5F5F5"
        ec = CB if "宛先" in fname else CGR
        rect_node(ax, x, y - 0.065, fw - 0.005, 0.055, fname,
                  fc=fc, ec=ec, tc=CB if "宛先" in fname else CGR, sz=8, bold=("宛先" in fname))
        x += fw
    ax.text(0.5, y - 0.005, "▲ IPパケットの構造（宛先IPアドレスを見てルーティングが行われる）",
            fontsize=8, color=CGR, ha="center", va="top", transform=ax.transAxes)
    y -= 0.10

    y = section(ax, y, "1.2　ルーティングテーブルとは？")
    T(ax, 0.02, y,
      "ルータは「ルーティングテーブル」という表を持っており、「宛先Xへ行くには次ホップYに転送する」\n"
      "という情報が書かれています。人間で言えば「道路地図」に相当します。",
      sz=9.5, c=CGR)
    y -= 0.07

    # ルーティングテーブル例
    table_data = [
        ("宛先ネットワーク",  "ネクストホップ",  "インタフェース", "メトリック"),
        ("10.20.0.0/16",    "10.0.1.2",      "leri-cr1",      "20"),
        ("192.168.0.5/32",  "10.0.1.2",      "leri-cr1",      "20"),
        ("0.0.0.0/0",       "(デフォルト)",   "—",             "—"),
    ]
    col_x = [0.02, 0.25, 0.50, 0.73]
    col_w = [0.22, 0.24, 0.22, 0.13]
    for ri, row in enumerate(table_data):
        fc = CB if ri == 0 else ("#EEF4FF" if ri % 2 == 1 else "white")
        tc = CW if ri == 0 else CGR
        for ci, (cell, cx, cw) in enumerate(zip(row, col_x, col_w)):
            rect_node(ax, cx, y - 0.032, cw - 0.005, 0.030, cell,
                      fc=fc, ec="#BDBDBD", tc=tc, sz=8 if ri > 0 else 8, bold=(ri == 0))
        y -= 0.032
    y -= 0.015

    y = section(ax, y, "1.3　静的ルーティング vs 動的ルーティング")
    col1 = [
        "■ 静的ルーティング",
        "  ・管理者が手動でテーブルを設定",
        "  ・シンプルだが柔軟性がない",
        "  ・リンク障害時に自動復旧しない",
        "  ・ノード数が増えると管理不可能",
    ]
    col2 = [
        "■ 動的ルーティング (OSPF など)",
        "  ・ルータが自動でテーブルを構築",
        "  ・障害発生時に自動で迂回経路を計算",
        "  ・大規模ネットワークに対応",
        "  ・本研究で採用 ← ここが OSPF",
    ]
    for i, (l1, l2) in enumerate(zip(col1, col2)):
        bold1 = i == 0
        bold2 = i == 0
        ax.text(0.02, y, l1, fontsize=9, color=CGR if i > 0 else CR,
                fontweight="bold" if bold1 else "normal", va="top",
                transform=ax.transAxes)
        ax.text(0.52, y, l2, fontsize=9, color=CGR if i > 0 else CG,
                fontweight="bold" if bold2 else "normal", va="top",
                transform=ax.transAxes)
        y -= 0.028
    y -= 0.01

    callout(ax, 0.02, y - 0.065, 0.96, 0.058,
            "【!】 本研究のポイント:  OSPF（動的ルーティング）を使うことで、\n"
            "   CR1 に障害が発生した際に CR2 / CR3 への自動迂回が実現する。"
            " これが「failure_reroute シナリオ」の核心技術。",
            fc="#E8F5E9", ec=CG, sz=9.5)

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

# ═══════════════════════════════════════════════════════════════════════════
# P3: 第2章 OSPF ① 隣接関係
# ═══════════════════════════════════════════════════════════════════════════
def page_ch2_adj(pdf):
    fig, ax = new_page("第 2 章　OSPF の仕組み ①　隣接関係の確立", "Open Shortest Path First")
    page_num(fig, 3)
    y = 0.97

    y = section(ax, y, "2.1　OSPF とは？")
    T(ax, 0.02, y,
      "OSPF（Open Shortest Path First）はルータ間でネットワークの「地図情報」を交換し合い、\n"
      "各ルータが独立して最短経路を計算するプロトコルです。\n"
      "「リンクステート型」と呼ばれ、リンクの状態（接続関係・コスト）を全ルータで共有します。",
      sz=9.5, c=CGR)
    y -= 0.085

    y = section(ax, y, "2.2　Hello パケットと隣接関係 (Adjacency)")
    T(ax, 0.02, y,
      "OSPF ルータは定期的に「Hello パケット」をリンクに送出します。\n"
      "同じリンクに接続された別のルータが Hello を受信すると、お互いを「ネイバー (Neighbor)」として認識し、\n"
      "その後データベースの同期を経て「Full 状態」（隣接完成）に遷移します。",
      sz=9.5, c=CGR)
    y -= 0.085

    # 状態遷移図
    states = [
        (0.05, "Down\n(初期)"),
        (0.23, "Init\n(Hello受信)"),
        (0.42, "2-Way\n(双方向確認)"),
        (0.61, "Exchange\n(DB交換中)"),
        (0.80, "Full\n(同期完了)"),
    ]
    sy = y - 0.02
    for sx, sname in states:
        fc = CL if "Full" not in sname else "#C8E6C9"
        ec = CB if "Full" not in sname else CG
        tc = CB if "Full" not in sname else CG
        rect_node(ax, sx, sy - 0.05, 0.15, 0.05, sname, fc=fc, ec=ec, tc=tc, sz=8)
        if sx < 0.80:
            arr(ax, sx + 0.155, sy - 0.025, sx + 0.22, sy - 0.025, color=CB, lw=1.3)
    ax.text(0.5, sy - 0.07, "▲ OSPF 状態遷移（Full 状態になって初めて経路情報が有効になる）",
            fontsize=8, color=CGR, ha="center", va="top", transform=ax.transAxes)
    y -= 0.11

    # Hello 設定
    y = section(ax, y, "2.3　Hello / Dead インターバル")
    T(ax, 0.02, y,
      "Hello パケットの送出間隔と、何秒間 Hello が届かなければリンク障害と判断するかの設定値です。",
      sz=9.5, c=CGR)
    y -= 0.04

    params = [
        ("hello-interval",    "1 秒",  "Hello パケット送出間隔（本研究の設定値、デフォルトは 10 秒）"),
        ("dead-interval",     "3 秒",  "この秒数 Hello が届かなければ隣接消滅と判断"),
        ("BFD (追加設定)",    "150 ms","50ms 間隔 × 3 回 = 150ms で障害検出（OSPFより高速）"),
    ]
    for p, v, desc in params:
        rect_node(ax, 0.02, y - 0.032, 0.20, 0.030, p,
                  fc=CL, ec=CB, tc=CB, sz=8.5, bold=True)
        rect_node(ax, 0.23, y - 0.032, 0.10, 0.030, v,
                  fc="#FFF9C4", ec="#F9A825", tc="#E65100", sz=9, bold=True)
        ax.text(0.35, y - 0.018, desc, fontsize=9, color=CGR,
                va="center", transform=ax.transAxes)
        y -= 0.038
    y -= 0.01

    # ネットワーク種別
    y = section(ax, y, "2.4　ネットワーク種別: Point-to-Point (P2P)")
    T(ax, 0.02, y,
      "OSPF にはリンクの種別（broadcast / P2P など）があり、本研究では全リンクを\n"
      "「ip ospf network point-to-point」に設定しています。これにより:\n"
      "  ・DR（Designated Router）選出が不要 → 収束が高速\n"
      "  ・2台のルータ間で直接隣接関係を確立 → シンプルな制御",
      sz=9.5, c=CGR)
    y -= 0.095

    # 本研究の構成
    callout(ax, 0.02, y - 0.105, 0.96, 0.098,
            "【!】 本研究での OSPF 隣接関係:\n"
            "   LER_Ingress ─── CR1  (leri-cr1 / cr1-leri, 10.0.1.0/30)\n"
            "   LER_Ingress ─── CR2  (leri-cr2 / cr2-leri, 10.0.3.0/30)\n"
            "   LER_Ingress ─── CR3  (leri-cr3 / cr3-leri, 10.0.5.0/30)\n"
            "   CR1 ─── LER_Egress  (cr1-lere / lere-cr1, 10.0.2.0/30)\n"
            "   ... 合計 6 本の OSPF 隣接 (全て Full 状態) で経路情報を共有",
            fc=CL, ec=CB, sz=9.3)

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

# ═══════════════════════════════════════════════════════════════════════════
# P4: 第2章 OSPF ② LSA / SPF
# ═══════════════════════════════════════════════════════════════════════════
def page_ch2_lsa(pdf):
    fig, ax = new_page("第 2 章　OSPF の仕組み ②　LSA / LSDB / SPF 計算", "Open Shortest Path First")
    page_num(fig, 4)
    y = 0.97

    y = section(ax, y, "2.5　LSA（Link State Advertisement）とは？")
    T(ax, 0.02, y,
      "隣接完成（Full 状態）後、各ルータは自分のリンク接続情報を「LSA」というパケットに\n"
      "まとめてフラッディング（全隣接ルータへ転送）します。\n"
      "これにより全ルータが同じ「ネットワーク地図」（LSDB）を持つことができます。",
      sz=9.5, c=CGR)
    y -= 0.085

    # LSAフラッディング図（絶対座標で配置）
    diag_top = y - 0.01
    box_h = 0.048
    leri_cy = diag_top - 0.095   # LER_Ingress / LER_Egress (中段)
    cr1_cy  = diag_top - 0.030   # CR1 (上段)
    cr2_cy  = diag_top - 0.095   # CR2 (中段)
    cr3_cy  = diag_top - 0.160   # CR3 (下段)
    rect_node(ax, 0.08, leri_cy - box_h/2, 0.12, box_h, "LER\nIngress", fc=CL, ec=CB, tc=CB, sz=8)
    rect_node(ax, 0.42, cr1_cy  - box_h/2, 0.12, box_h, "CR1", fc=CGL, ec=CG, tc=CG, sz=8)
    rect_node(ax, 0.42, cr2_cy  - box_h/2, 0.12, box_h, "CR2", fc=CGL, ec=CG, tc=CG, sz=8)
    rect_node(ax, 0.42, cr3_cy  - box_h/2, 0.12, box_h, "CR3", fc=CGL, ec=CG, tc=CG, sz=8)
    rect_node(ax, 0.76, leri_cy - box_h/2, 0.12, box_h, "LER\nEgress", fc=CL, ec=CB, tc=CB, sz=8)
    arr(ax, 0.20, leri_cy, 0.42, cr1_cy,  color=CB, lw=1.2, style="<->")
    arr(ax, 0.20, leri_cy, 0.42, cr2_cy,  color=CB, lw=1.2, style="<->")
    arr(ax, 0.20, leri_cy, 0.42, cr3_cy,  color=CB, lw=1.2, style="<->")
    arr(ax, 0.54, cr1_cy,  0.76, leri_cy, color=CB, lw=1.2, style="<->")
    arr(ax, 0.54, cr2_cy,  0.76, leri_cy, color=CB, lw=1.2, style="<->")
    arr(ax, 0.54, cr3_cy,  0.76, leri_cy, color=CB, lw=1.2, style="<->")
    ax.text(0.5, diag_top - 0.210, "▲ 各ルータが LSA をフラッディングし、全ルータが同じ LSDB を持つ",
            fontsize=8, color=CGR, ha="center", va="top", transform=ax.transAxes)
    y -= 0.250

    y = section(ax, y, "2.6　SPF 計算（Dijkstra 法）")
    T(ax, 0.02, y,
      "全ルータが同じ LSDB（ネットワーク地図）を持ったら、各ルータは独立して\n"
      "Dijkstra アルゴリズムで「自分から全宛先への最短経路」を計算します。\n"
      "この計算結果がルーティングテーブルに書き込まれます。",
      sz=9.5, c=CGR)
    y -= 0.085

    # SPF 計算例
    T(ax, 0.02, y, "【例】LER_Ingress → LER_Egress (192.168.0.5) の最短経路:", sz=9.5, c=CB, bold=True)
    y -= 0.03
    paths = [
        ("経路①", "LER_Ingress → CR1 → LER_Egress", "コスト 20", CG),
        ("経路②", "LER_Ingress → CR2 → LER_Egress", "コスト 20", CG),
        ("経路③", "LER_Ingress → CR3 → LER_Egress", "コスト 20", CG),
    ]
    for pname, pdesc, pcost, pc in paths:
        ax.text(0.05, y, pname, fontsize=9.5, color=pc, fontweight="bold",
                va="top", transform=ax.transAxes)
        ax.text(0.14, y, pdesc, fontsize=9.5, color=CGR,
                va="top", transform=ax.transAxes)
        ax.text(0.74, y, pcost, fontsize=9.5, color=CO, fontweight="bold",
                va="top", transform=ax.transAxes)
        y -= 0.03
    T(ax, 0.05, y, "→ 3 経路が等コスト (ECMP: Equal Cost Multi-Path) → ロードバランシング",
      sz=9.5, c=CB, bold=False)
    y -= 0.04

    y = section(ax, y, "2.7　Opaque LSA と OSPF-SR への拡張")
    T(ax, 0.02, y,
      "通常の LSA はリンク接続情報のみを配布しますが、「Opaque LSA」（Type 9/10）という\n"
      "拡張 LSA を使うと、任意の情報を LSDB に載せてフラッディングできます。\n"
      "OSPF-SR（Segment Routing）では Opaque LSA を使って「ラベル番号（SID）」を配布します。\n"
      "本研究でも show ip ospf database で Opaque-Type 7/8 の LSA が確認できています。",
      sz=9.5, c=CGR)
    y -= 0.105

    callout(ax, 0.02, y - 0.065, 0.96, 0.058,
            "【!】 まとめ:  OSPF = (1) Hello で隣接確立 → (2) LSA をフラッディング →\n"
            "   (3) LSDB を全ルータで共有 → (4) SPF で最短経路計算 → (5) ルーティングテーブル完成",
            fc=CL, ec=CB, sz=9.5)

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

# ═══════════════════════════════════════════════════════════════════════════
# P5: 第3章 MPLS ① 基礎
# ═══════════════════════════════════════════════════════════════════════════
def page_ch3_intro(pdf):
    fig, ax = new_page("第 3 章　MPLS の仕組み ①　ラベル転送の基礎", "Multi-Protocol Label Switching")
    page_num(fig, 5)
    y = 0.97

    y = section(ax, y, "3.1　MPLS とは？　─ IP ルーティングの限界と解決策")
    T(ax, 0.02, y,
      "通常の IP 転送では、ルータはパケットが届くたびに宛先 IP をルーティングテーブルで\n"
      "検索（Longest Prefix Match）します。大規模ネットワークではこれが遅延・CPU負荷に。\n\n"
      "MPLS（Multi-Protocol Label Switching）は IP ヘッダの前に短い「ラベル（20bit 整数）」を\n"
      "付けて転送を行います。ルータはラベルだけを見て転送するので非常に高速です。\n"
      "また、同じ宛先 IP でもラベルを変えることで異なる経路に誘導できます（Traffic Engineering）。",
      sz=9.5, c=CGR)
    y -= 0.125

    y = section(ax, y, "3.2　MPLS ラベルの構造")
    # ラベルスタック図
    fields32 = [
        ("ラベル値 (20 bit)\n転送先を決める整数", 0.40),
        ("TC\n(3 bit)", 0.12),
        ("S\n(1 bit)", 0.08),
        ("TTL\n(8 bit)", 0.16),
    ]
    lx = 0.05
    for fname, fw in fields32:
        fc = CL if "ラベル" in fname else "#F5F5F5"
        ec = CB if "ラベル" in fname else CGR
        rect_node(ax, lx, y - 0.065, fw - 0.005, 0.058, fname,
                  fc=fc, ec=ec, tc=CB if "ラベル" in fname else CGR, sz=8,
                  bold=("ラベル" in fname))
        lx += fw
    ax.text(0.5, y - 0.075, "▲ MPLS ラベル（32 bit = 4 バイト）の構造",
            fontsize=8, color=CGR, ha="center", va="top", transform=ax.transAxes)
    y -= 0.10

    tc_desc = [
        ("ラベル値 (20 bit)", "転送先を決める整数値。本研究では 16001〜16005 を使用"),
        ("TC (3 bit)",       "Traffic Class: DiffServ に相当、本研究では DSCP と連動"),
        ("S (1 bit)",        "Stack Bottom: ラベルスタックの最後の 1 枚なら 1（本研究では単一ラベル）"),
        ("TTL (8 bit)",      "Time To Live: ループ防止カウンタ（IP の TTL と同様）"),
    ]
    for fname, fdesc in tc_desc:
        ax.text(0.05, y, f"・{fname}:", fontsize=9.5, color=CB, fontweight="bold",
                va="top", transform=ax.transAxes)
        ax.text(0.32, y, fdesc, fontsize=9.5, color=CGR,
                va="top", transform=ax.transAxes)
        y -= 0.028
    y -= 0.01

    y = section(ax, y, "3.3　ノードの役割: LER と LSR")
    roles = [
        ("LER\n(Label Edge Router)",
         "ラベルを付けたり外したりするエッジルータ。\n"
         "本研究: LER_Ingress（ラベル付与）、LER_Egress（ラベル除去）",
         CL, CB),
        ("LSR\n(Label Switching Router)",
         "ラベルを見て転送するコアルータ（IP を見ない）。\n"
         "本研究: CR1 / CR2 / CR3 がこの役割",
         CGL, CG),
    ]
    for rname, rdesc, fc, ec in roles:
        rect_node(ax, 0.02, y - 0.070, 0.18, 0.065, rname, fc=fc, ec=ec, tc=ec, sz=9, bold=True)
        ax.text(0.225, y - 0.010, rdesc, fontsize=9.5, color=CGR,
                va="top", transform=ax.transAxes, multialignment="left")
        y -= 0.082
    y -= 0.005

    callout(ax, 0.02, y - 0.075, 0.96, 0.068,
            "【!】 MPLS のメリット（本研究での意義）:\n"
            "   ・同じ 10.20.0.0/16 宛パケットでも、DSCP クラス (AF41/42/43) ごとに\n"
            "     異なるラベルを使って CR1/CR2/CR3 の「異なるキュー」に誘導できる。\n"
            "     これが DiffServ-TE（クラス別トラフィックエンジニアリング）の仕組み。",
            fc=COL, ec=CO, sz=9.3)

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

# ═══════════════════════════════════════════════════════════════════════════
# P6: 第3章 MPLS ② PUSH/SWAP/POP
# ═══════════════════════════════════════════════════════════════════════════
def page_ch3_forward(pdf):
    fig, ax = new_page("第 3 章　MPLS の仕組み ②　転送動作 PUSH / SWAP / POP", "Multi-Protocol Label Switching")
    page_num(fig, 6)
    y = 0.97

    y = section(ax, y, "3.4　3 つの転送操作")
    ops = [
        ("PUSH",  "LER_Ingress で\nラベルを付加", "IP パケット入力 → [ラベル|IP データ] 出力", CL, CB, "付加"),
        ("SWAP",  "LSR (CR1 等) で\nラベルを置換", "[旧ラベル|データ] → [新ラベル|データ]",     CGL, CG, "置換"),
        ("POP",   "LER_Egress で\nラベルを除去", "[ラベル|IP データ] → IP パケット出力",       COL, CO, "除去"),
    ]
    for ox, (oname, odesc, oex, ofc, oec, oact) in zip([0.02, 0.35, 0.68], ops):
        rect_node(ax, ox, y - 0.090, 0.29, 0.085, f"{oname}\n({oact})\n\n{odesc}",
                  fc=ofc, ec=oec, tc=oec, sz=9, bold=False)
    y -= 0.105

    # 転送フロー大図
    y = section(ax, y, "3.5　本研究での MPLS 転送フロー（全体像）")

    fy = y - 0.08
    # ノード
    nodes_info = [
        (0.02, "Tx1\n10.10.1.1"),
        (0.19, "LER_Ingress\n192.168.0.1"),
        (0.46, "CR1\n192.168.0.2"),
        (0.71, "LER_Egress\n192.168.0.5"),
        (0.88, "Rx1\n10.20.1.1"),
    ]
    for nx, nlbl in nodes_info:
        fc = CGL if "CR" in nlbl else CL
        ec = CG  if "CR" in nlbl else CB
        rect_node(ax, nx, fy - 0.048, 0.15, 0.045, nlbl,
                  fc=fc, ec=ec, tc=ec, sz=7.5, bold=False)
    # アロー
    xs = [0.02, 0.19, 0.46, 0.71, 0.88]
    for i in range(len(xs)-1):
        arr(ax, xs[i]+0.15, fy-0.025, xs[i+1], fy-0.025, color=CB, lw=1.5)

    # 各段階でのパケット表示
    packets = [
        (0.02,  fy-0.055, "[IP src=10.10.1.1\ndst=10.20.1.1]", "#FFF9C4", "#F9A825"),
        (0.24,  fy-0.055, "[label=16005\nIP dst=10.20.1.1]",    CL, CB),
        (0.50,  fy-0.055, "[label=16005\nIP dst=10.20.1.1]",    CGL, CG),
        (0.76,  fy-0.055, "[IP src=10.10.1.1\ndst=10.20.1.1]", "#FFF9C4", "#F9A825"),
    ]
    for px, py, plbl, pfc, pec in packets:
        rect_node(ax, px, py-0.038, 0.16, 0.036, plbl, fc=pfc, ec=pec, tc=pec, sz=7, bold=False)

    # 操作ラベル (ノードボックスより上に配置)
    ops_pos = [
        (0.215, fy+0.015, "PUSH\nlabel 16005", CB),
        (0.52,  fy+0.015, "SWAP\n(同じラベル)", CG),
        (0.73,  fy+0.015, "POP\nラベル除去", CO),
    ]
    for opx, opy, opl, opc in ops_pos:
        rect_node(ax, opx, opy, 0.12, 0.038, opl, fc="white", ec=opc, tc=opc, sz=8, bold=True)

    y -= 0.210

    y = section(ax, y, "3.6　本研究の MPLS テーブル（show mpls table の読み方）")
    T(ax, 0.02, y,
      "LER_Ingress で実際に確認できた MPLS テーブルを解説します:", sz=9.5, c=CGR)
    y -= 0.03

    mpls_rows = [
        ("InLabel", "Type",     "Nexthop",   "OutLabel",       "意味"),
        ("16001",   "SR(OSPF)", "lo",         "—",             "自分自身の Node SID → lo (loopback)"),
        ("16002",   "SR(OSPF)", "10.0.1.2",   "16002",         "CR1 の SID → leri-cr1 経由で転送"),
        ("16003",   "SR(OSPF)", "10.0.3.2",   "16003",         "CR2 の SID → leri-cr2 経由で転送"),
        ("16005",   "SR(OSPF)", "10.0.1.2",   "16005",         "LER_Egress の SID (ECMP 3 経路)"),
        ("16005",   "SR(OSPF)", "10.0.3.2",   "16005",         "           ↑ CR2 経由"),
        ("16005",   "SR(OSPF)", "10.0.5.2",   "16005",         "           ↑ CR3 経由"),
    ]
    col_x = [0.02, 0.12, 0.22, 0.35, 0.49]
    col_w = [0.09, 0.09, 0.12, 0.13, 0.49]
    for ri, row in enumerate(mpls_rows):
        fc = CB if ri == 0 else ("white" if ri % 2 == 1 else "#F5F5F5")
        tc = CW if ri == 0 else CGR
        hl = ri >= 4  # highlight ECMP rows
        for ci, (cell, cx, cw) in enumerate(zip(row, col_x, col_w)):
            fc2 = "#FFF9C4" if hl and ci in [0,1,2,3] else fc
            ec2 = CO if hl and ci in [0] else "#BDBDBD"
            rect_node(ax, cx, y - 0.028, cw - 0.003, 0.027, cell,
                      fc=fc2 if ri > 0 else CB,
                      ec=ec2 if ri > 0 else CB,
                      tc=CO if hl and ci == 0 and ri > 0 else (CW if ri == 0 else CGR),
                      sz=7.5 if ri > 0 else 8, bold=(ri == 0))
        y -= 0.028
    y -= 0.01

    T(ax, 0.02, y, "※ implicit-null: PHP (Penultimate Hop Popping)。1 つ手前のルータがラベルを除去する最適化。",
      sz=9, c=CGR)

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

# ═══════════════════════════════════════════════════════════════════════════
# P7: 第4章 Segment Routing ① 概要
# ═══════════════════════════════════════════════════════════════════════════
def page_ch4_intro(pdf):
    fig, ax = new_page("第 4 章　Segment Routing (SR)　①　概要と設計思想", "OSPF-SR / SR-MPLS")
    page_num(fig, 7)
    y = 0.97

    y = section(ax, y, "4.1　Segment Routing とは？")
    T(ax, 0.02, y,
      "Segment Routing (SR) は「Source Routing（送信元ルーティング）」の現代的な実装です。\n"
      "従来の MPLS では各 LSR が LDP/RSVP というシグナリングプロトコルでラベルを管理しましたが、\n"
      "SR では OSPF（または BGP/IS-IS）の拡張だけでラベルを配布するため\n"
      "設定がシンプルで、状態管理（シグナリングプロトコルのセッション）が不要です。",
      sz=9.5, c=CGR)
    y -= 0.095

    # 比較表
    y = section(ax, y, "4.2　従来 MPLS (LDP/RSVP) vs Segment Routing")
    headers = ["",  "従来 MPLS (LDP/RSVP)", "Segment Routing (本研究)"]
    rows = [
        ["ラベル配布",   "LDP / RSVP-TE (別プロトコル)", "OSPF 拡張 (Opaque LSA) のみ"],
        ["状態管理",     "全 LSR でセッション管理が必要",   "不要（ステートレス）"],
        ["設定複雑度",   "複雑（多数のコンフィグ）",        "シンプル（OSPF 設定の延長）"],
        ["TI-LFA",      "困難",                           "標準対応（高速迂回）"],
        ["本研究採用",   "─",                             "✓  採用"],
    ]
    col_x = [0.02, 0.25, 0.62]
    col_w = [0.22, 0.36, 0.36]
    for ri, row in enumerate(([headers] + rows)):
        fc = CB if ri == 0 else ("white" if ri % 2 == 1 else "#F5F5F5")
        tc = CW if ri == 0 else CGR
        for ci, (cell, cx, cw) in enumerate(zip(row, col_x, col_w)):
            hl = (ri > 0 and ci == 2)
            rect_node(ax, cx, y - 0.030, cw - 0.004, 0.028, cell,
                      fc="#E8F5E9" if hl else fc,
                      ec=CG if hl else "#BDBDBD",
                      tc=CG if hl else tc,
                      sz=8.5 if ri == 0 else 8.5, bold=(ri == 0 or (ri > 0 and ci == 2 and "✓" in cell)))
        y -= 0.030
    y -= 0.01

    y = section(ax, y, "4.3　Segment の概念")
    T(ax, 0.02, y,
      "SR では転送経路を「Segment（区間）」の列として表現します。\n"
      "各 Segment には SID（Segment ID）と呼ばれる識別子が付いており、\n"
      "SR-MPLS では SID が MPLS ラベル値になります。",
      sz=9.5, c=CGR)
    y -= 0.075

    sids = [
        ("Node SID\n(Prefix SID)",
         "ルータのループバック (lo) に対応する SID。\n"
         "そのルータに到達するための MPLS ラベルを表す。\n"
         "本研究: LER_Egress の Node SID = 16005",
         CL, CB),
        ("Adjacency SID\n(Adj-SID)",
         "特定のリンク（隣接）を指定する SID。\n"
         "15000 番台（本研究のテーブルに 15000-15005 が見える）。\n"
         "ローカルに割り当てられ、OSPF フラッディングで配布。",
         CGL, CG),
    ]
    for sname, sdesc, fc, ec in sids:
        rect_node(ax, 0.02, y - 0.075, 0.22, 0.070, sname, fc=fc, ec=ec, tc=ec, sz=9, bold=True)
        ax.text(0.26, y - 0.010, sdesc, fontsize=9.2, color=CGR,
                va="top", transform=ax.transAxes, multialignment="left")
        y -= 0.085

    callout(ax, 0.02, y - 0.055, 0.96, 0.048,
            "【!】 本研究での SID 設計:   SRGB（共通ラベル空間）= 16000 〜 23999\n"
            "   LER_Ingress=16001 / CR1=16002 / CR2=16003 / CR3=16004 / LER_Egress=16005",
            fc=COL, ec=CO, sz=9.5)

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

# ═══════════════════════════════════════════════════════════════════════════
# P8: 第4章 SR ② SRGB / 転送フロー
# ═══════════════════════════════════════════════════════════════════════════
def page_ch4_srgb(pdf):
    fig, ax = new_page("第 4 章　Segment Routing ②　SRGB / SR-MPLS 転送フロー", "OSPF-SR / SR-MPLS")
    page_num(fig, 8)
    y = 0.97

    y = section(ax, y, "4.4　SRGB（Segment Routing Global Block）")
    T(ax, 0.02, y,
      "SRGB は全ルータが共通で使うラベルの「予約範囲」です。\n"
      "この範囲内のラベルは「グローバルな意味を持つ SID」として扱われ、\n"
      "どのルータから見ても同じ宛先を指します。\n\n"
      "  ・本研究の設定: segment-routing global-block 16000 23999\n"
      "  ・Node SID = SRGB_BASE(16000) + index\n"
      "  ・例: LER_Egress (index=5) → 16000 + 5 = 16005",
      sz=9.5, c=CGR)
    y -= 0.115

    # SRGB 図
    bar_y = y - 0.04
    ax.add_patch(mpatches.Rectangle((0.05, bar_y), 0.90, 0.028,
                                     facecolor="#E0E0E0", edgecolor="#BDBDBD", lw=1,
                                     transform=ax.transAxes))
    ax.text(0.05, bar_y + 0.035, "ラベル空間", fontsize=8, color=CGR,
            va="bottom", transform=ax.transAxes)
    ax.text(0.0,  bar_y + 0.014, "0", fontsize=7, color=CGR,
            ha="left", va="center", transform=ax.transAxes)

    srgb_start = 0.05 + (16000 / 25000) * 0.90
    srgb_w     = (8000 / 25000) * 0.90
    ax.add_patch(mpatches.Rectangle((srgb_start, bar_y), srgb_w, 0.028,
                                     facecolor=CL, edgecolor=CB, lw=2,
                                     transform=ax.transAxes))
    ax.text(srgb_start + srgb_w/2, bar_y + 0.014,
            "SRGB: 16000〜23999", fontsize=8.5, color=CB, fontweight="bold",
            ha="center", va="center", transform=ax.transAxes)

    sids_pos = [
        (1, "#1565C0"), (2, "#0097A7"), (3, "#00838F"),
        (4, "#006064"), (5, "#E65100"),
    ]
    for idx, sc in sids_pos:
        sx = srgb_start + (idx * 0.008)
        ax.plot([sx, sx], [bar_y - 0.005, bar_y + 0.028], color=sc, lw=1.5,
                transform=ax.transAxes)

    ax.text(0.97, bar_y + 0.014, "65535", fontsize=7, color=CGR,
            ha="right", va="center", transform=ax.transAxes)
    y -= 0.085

    y = section(ax, y, "4.5　SR-MPLS 転送フロー（単一ラベルでエンドツーエンド）")
    T(ax, 0.02, y,
      "本研究での最大の特徴:「ラベル 16005 を 1 枚付けるだけで Tx → Rx まで届く」。\n"
      "各 LSR (CR1/2/3) は宛先 IP を見ずにラベルだけで転送するため、\n"
      "障害時のルート変更もラベルのネクストホップを変えるだけで完了します。",
      sz=9.5, c=CGR)
    y -= 0.085

    # 詳細な転送フロー
    flow_steps = [
        ("①", "Tx1 が IP パケットを送信",
         "src=10.10.1.1, dst=10.20.1.1\nDSCP=AF41 (DSCP 値 34)"),
        ("②", "LER_Ingress が PUSH",
         "ip rule: DSCP AF41 → table 41\n"
         "table 41: 10.20.0.0/16 via 10.0.1.2 encap mpls 16005\n"
         "→ [label=16005 | IP] を leri-cr1 から出力"),
        ("③", "CR1 が SWAP (label 16005 → 16005)",
         "show mpls table: 16005 → nexthop 10.0.2.1 outlab 16005\n"
         "ラベルは同じだがネクストホップが LER_Egress 方向に変わる"),
        ("④", "LER_Egress が POP",
         "自分の Node SID (16005) が着信 → ラベルを除去\n"
         "普通の IP パケットとして Rx1 に転送"),
    ]
    for step, title, detail in flow_steps:
        rect_node(ax, 0.02, y - 0.068, 0.04, 0.063, step,
                  fc=CB, ec=CB, tc=CW, sz=12, bold=True)
        ax.text(0.08, y - 0.005, title, fontsize=10, color=CB, fontweight="bold",
                va="top", transform=ax.transAxes)
        ax.text(0.08, y - 0.025, detail, fontsize=8.5, color=CGR,
                va="top", transform=ax.transAxes, multialignment="left")
        hr(ax, y - 0.072, alpha=0.12)
        y -= 0.078

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

# ═══════════════════════════════════════════════════════════════════════════
# P9: 第5章 本研究ラボでの動作
# ═══════════════════════════════════════════════════════════════════════════
def page_ch5_lab(pdf):
    fig, ax = new_page("第 5 章　本研究ラボでの動作　①　DiffServ-TE + WRR QoS", "ラボ統合動作")
    page_num(fig, 9)
    y = 0.97

    y = section(ax, y, "5.1　本研究のトポロジーと役割")
    T(ax, 0.02, y,
      "本研究は OSPF-SR によるトラフィックエンジニアリングと DiffServ QoS を組み合わせた\n"
      "「クラス別 SLA 保証」を評価するラボ実験です。3 つのトラフィッククラスを\n"
      "1 本のリンク上で WRR により帯域分配します。",
      sz=9.5, c=CGR)
    y -= 0.115

    # 完全なトポロジー図
    ty = y - 0.01
    # Tx群
    for i, (tname, tip) in enumerate([("Tx1","10.10.1.1"),("Tx2","10.10.2.1"),("Tx3","10.10.3.1")]):
        rect_node(ax, 0.00, ty - i*0.082, 0.10, 0.065, f"{tname}\n{tip}",
                  fc="#FFF9C4", ec="#F9A825", tc="#E65100", sz=7.5)
    # LER_Ingress (Tx3底面 ty-0.164 から Tx1天面 ty+0.065 まで span)
    rect_node(ax, 0.16, ty - 0.164, 0.14, 0.229,
              "LER_Ingress\n192.168.0.1\n\nDSCP分類\nMPLS PUSH\nHTB WRR",
              fc=CL, ec=CB, tc=CB, sz=7.5)
    # CR群
    for i, (cname, cip) in enumerate([("CR1","192.168.0.2"),("CR2","192.168.0.3"),("CR3","192.168.0.4")]):
        fc = CGL if i == 0 else "#F9FBE7"
        ec = CG  if i == 0 else "#9CCC65"
        rect_node(ax, 0.38, ty - i*0.082, 0.14, 0.065, f"{cname}\n{cip}\nOSPF-SR LSR",
                  fc=fc, ec=ec, tc=ec, sz=7.5)
    # LER_Egress
    rect_node(ax, 0.60, ty - 0.164, 0.14, 0.229,
              "LER_Egress\n192.168.0.5\n\nMPLS POP\nIP転送",
              fc=CL, ec=CB, tc=CB, sz=7.5)
    # Rx群
    for i, (rname, rip) in enumerate([("Rx1","10.20.1.1"),("Rx2","10.20.2.1"),("Rx3","10.20.3.1")]):
        rect_node(ax, 0.80, ty - i*0.082, 0.10, 0.065, f"{rname}\n{rip}",
                  fc="#E8F5E9", ec="#66BB6A", tc=CG, sz=7.5)

    # リンク描画
    for i in range(3):
        arr(ax, 0.10, ty - i*0.082 + 0.032, 0.16, ty - 0.082 + 0.032 + i*0.000,
            color="#F9A825", lw=1.2)
        arr(ax, 0.30, ty - i*0.082 + 0.032, 0.38, ty - i*0.082 + 0.032,
            color=CG, lw=1.4)
        arr(ax, 0.52, ty - i*0.082 + 0.032, 0.60, ty - 0.082 + 0.032,
            color=CG, lw=1.4)
        arr(ax, 0.74, ty - 0.082 + 0.032, 0.80, ty - i*0.082 + 0.032,
            color="#66BB6A", lw=1.2)

    # ラベル表示 (ダイアグラム下部 CR3 底面より下)
    ax.text(0.34, ty - 0.178, "HTB WRR\n4:2:1 / 100Mbps",
            fontsize=7.5, color=CO, ha="center", va="top",
            transform=ax.transAxes,
            bbox=dict(fc=COL, ec=CO, pad=2, boxstyle="round"))

    y -= 0.255

    y = section(ax, y, "5.2　DiffServ クラス分類（DSCP → fwmark → ポリシールーティング）")
    rows = [
        ("クラス", "DSCP 値", "fwmark", "policy table", "WRR 帯域",   "用途"),
        ("AF41",  "34",      "41",      "table 41",     "57 Mbps (4)", "高優先（最優先保証）"),
        ("AF42",  "36",      "42",      "table 42",     "28 Mbps (2)", "中優先"),
        ("AF43",  "38",      "43",      "table 43",     "14 Mbps (1)", "低優先（ベストエフォート）"),
    ]
    cx = [0.02, 0.12, 0.21, 0.30, 0.43, 0.57]
    cw = [0.09, 0.08, 0.08, 0.12, 0.14, 0.41]
    for ri, row in enumerate(rows):
        fc = CB if ri == 0 else (["#E3F2FD", "#FFF3E0", "#E8F5E9"][ri-1] if ri > 0 else "white")
        tc = CW if ri == 0 else CGR
        for ci, (cell, cxi, cwi) in enumerate(zip(row, cx, cw)):
            rect_node(ax, cxi, y - 0.028, cwi - 0.003, 0.026, cell,
                      fc=fc if ri > 0 else CB, ec="#BDBDBD" if ri > 0 else CB,
                      tc=tc, sz=8 if ri == 0 else 8.5, bold=(ri == 0))
        y -= 0.028
    y -= 0.015

    callout(ax, 0.02, y - 0.058, 0.96, 0.051,
            "【!】 処理の流れ:  Tx が DSCP を付けた UDP → LER_Ingress の iptables が DSCP を読んで fwmark 設定\n"
            "   → ip rule が fwmark に応じた policy table を選択 → table41/42/43 の encap mpls ルートで転送",
            fc=CL, ec=CB, sz=9.2)

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

# ═══════════════════════════════════════════════════════════════════════════
# P10: 第5章 障害検出・TI-LFA・収束
# ═══════════════════════════════════════════════════════════════════════════
def page_ch5_failure(pdf):
    fig, ax = new_page("第 5 章　本研究ラボでの動作　②　障害検出・迂回・収束", "ラボ統合動作")
    page_num(fig, 10)
    y = 0.97

    y = section(ax, y, "5.3　BFD（Bidirectional Forwarding Detection）")
    T(ax, 0.02, y,
      "OSPF の障害検出は dead-interval（本研究では 3 秒）が基本ですが、\n"
      "BFD を併用することでこれを大幅に短縮できます。\n\n"
      "BFD は専用の軽量 Hello パケットを高頻度で送受信し、\n"
      "応答が途絶えたら即座に OSPF に通知してリンクを down 扱いにします。",
      sz=9.5, c=CGR)
    y -= 0.095

    # BFD タイムライン図
    tl_y = y - 0.04
    ax.plot([0.05, 0.95], [tl_y, tl_y], color=CB, lw=2, transform=ax.transAxes)
    events = [
        (0.05, "t=0\n開始"),
        (0.25, "t=50ms\n1回目失敗"),
        (0.50, "t=100ms\n2回目失敗"),
        (0.72, "t=150ms\n3回目失敗\n→ BFD DOWN"),
        (0.88, "t≈200ms\nOSPF 隣接\n消滅"),
    ]
    for ex, elbl in events:
        ax.plot(ex, tl_y, "o", ms=7, color=CR if "DOWN" in elbl or "消滅" in elbl else CB,
                transform=ax.transAxes, zorder=3)
        ax.text(ex, tl_y - 0.015, elbl, fontsize=7.5, color=CR if "DOWN" in elbl or "消滅" in elbl else CB,
                ha="center", va="top", transform=ax.transAxes, multialignment="center")
    ax.text(0.5, tl_y + 0.025, "BFD 検出タイムライン (receive-interval=50ms, detect-multiplier=3)",
            fontsize=8, color=CGR, ha="center", va="bottom", transform=ax.transAxes)
    y -= 0.115

    y = section(ax, y, "5.4　障害発生から迂回完了までの流れ (failure_reroute シナリオ)")
    steps_fail = [
        ("t = 0s",    "正常運用中。全クラス leri-cr1 (CR1) 経由。label 16005 で転送。"),
        ("t = 20s",   "ip link set leri-cr1 down を実行 → CR1 リンクが物理的に down。"),
        ("~20.15s",   "BFD が 150ms で検出 → OSPF に通知。FRR が隣接を即座に削除。"),
        ("~20.2s",    "frr_te_monitor が operstate (leri-cr1 = down) を検知。"),
        ("~20.2〜1s", "OSPF 収束待ち (wait_ospf_converge): 192.168.0.2 の隣接消滅を確認。"),
        ("~21s",      "update_tables() 実行: table41/42/43 の nexthop を leri-cr2 (CR2) に変更。"),
        ("~21s〜",    "全クラスが CR2 経由で転送再開。実測収束時間: AF41/AF42/AF43 いずれも約 1 秒。"),
        ("t = 40s",   "leri-cr1 up → OSPF Full 確立後に CR1 へ自動復元。"),
    ]
    for tstamp, desc in steps_fail:
        rect_node(ax, 0.02, y - 0.030, 0.16, 0.027, tstamp,
                  fc="#FFF3E0" if "20s" in tstamp or "21s" in tstamp else CL,
                  ec=CO if "20s" in tstamp or "21s" in tstamp else CB,
                  tc=CO if "20s" in tstamp or "21s" in tstamp else CB,
                  sz=8, bold=True)
        ax.text(0.20, y - 0.016, desc, fontsize=9, color=CGR,
                va="center", transform=ax.transAxes)
        hr(ax, y - 0.033, alpha=0.08)
        y -= 0.038
    y -= 0.005

    y = section(ax, y, "5.5　TI-LFA（Topology Independent LFA）")
    T(ax, 0.02, y,
      "本研究の FRR 設定には fast-reroute ti-lfa が有効化されています。\n"
      "TI-LFA は障害発生時に「バックアップパス」を事前計算しておき、\n"
      "BFD 検出後ほぼ即座（50ms 以内）にパケットを迂回させる技術です。\n"
      "frr_te_monitor による動的ルート切替（~1 秒）より高速ですが、\n"
      "本研究では frr_te_monitor による収束時間を主に評価しています。",
      sz=9.5, c=CGR)
    y -= 0.105

    callout(ax, 0.02, y - 0.082, 0.96, 0.095,
            "【!】 本研究の実測収束時間 (failure_reroute, throughput.csv より):\n"
            "   AF41 (高優先 / WRR 57Mbps):  収束 1.0 秒\n"
            "   AF42 (中優先 / WRR 28Mbps):  収束 1.0 秒\n"
            "   AF43 (低優先 / WRR 14Mbps):  収束 1.0 秒\n"
            "   → OSPF dead-interval=3s より大幅に速い (BFD 150ms 検出 + OSPF 即時収束の効果)",
            fc="#E8F5E9", ec=CG, sz=9.3)

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

# ═══════════════════════════════════════════════════════════════════════════
# P11: 用語集
# ═══════════════════════════════════════════════════════════════════════════
def page_glossary(pdf):
    fig, ax = new_page("用語集　&　本研究の設定値一覧", "まとめ")
    page_num(fig, 11)
    y = 0.97

    y = section(ax, y, "用語集（アルファベット順）")

    terms = [
        ("Adj-SID",      "Adjacency SID。特定リンクを指定する SR ラベル (本研究: 15000 台)"),
        ("BFD",          "Bidirectional Forwarding Detection。50ms 周期の高速障害検出プロトコル"),
        ("DiffServ",     "Differentiated Services。DSCP 値でトラフィッククラスを区別する QoS"),
        ("DSCP",         "Differentiated Services Code Point。IPヘッダ 6bit の優先度フィールド"),
        ("ECMP",         "Equal Cost Multi-Path。同コストの複数経路をロードバランシング"),
        ("FRR",          "FRRouting。本研究で使用するオープンソースルーティングソフトウェア"),
        ("HTB",          "Hierarchical Token Bucket。Linux のクラスベース帯域制御 qdisc"),
        ("LDP",          "Label Distribution Protocol。従来 MPLS のラベル配布プロトコル"),
        ("LER",          "Label Edge Router。MPLS ドメインの境界でラベルを付与/除去"),
        ("LFIB",         "Label Forwarding Information Base。MPLS 転送テーブル"),
        ("LSA",          "Link State Advertisement。OSPF がフラッディングするリンク情報"),
        ("LSDB",         "Link State Database。全ルータが共有する OSPF のネットワーク地図"),
        ("LSR",          "Label Switching Router。ラベルのみで転送するコアルータ"),
        ("MPLS",         "Multi-Protocol Label Switching。ラベルによる高速パケット転送"),
        ("netem",        "Network Emulator。Linux でパケット遅延/損失を付与するqdisc"),
        ("Node SID",     "ルータのLoopbackに対応するSR SID。本研究: 16001〜16005"),
        ("OSPF",         "Open Shortest Path First。リンクステート型動的ルーティングプロトコル"),
        ("OWD",          "One-Way Delay。送信側→受信側の片道遅延時間"),
        ("PHP",          "Penultimate Hop Popping。最終ホップ 1 つ前でラベルを除去する最適化"),
        ("SRGB",         "Segment Routing Global Block。SR の共通ラベル予約範囲 (本研究: 16000-23999)"),
        ("SR-MPLS",      "Segment Routing over MPLS データプレーン"),
        ("SPF",          "Shortest Path First (Dijkstra 法)。OSPF が最短経路を計算するアルゴリズム"),
        ("TI-LFA",       "Topology Independent LFA。SR を利用した高速バックアップパス事前計算"),
        ("WRR",          "Weighted Round Robin。重み付き帯域配分 (本研究: AF41:AF42:AF43 = 4:2:1)"),
    ]
    for i, (term, desc) in enumerate(terms):
        tc = CB if i < 12 else CO
        ax.text(0.01, y, term, fontsize=8.5, color=tc, fontweight="bold",
                va="top", transform=ax.transAxes)
        ax.text(0.14, y, desc, fontsize=8.0, color=CGR,
                va="top", transform=ax.transAxes)
        y -= 0.023
    y -= 0.01

    y = section(ax, y, "本研究の主要設定値一覧")
    settings = [
        ("OSPF hello-interval",     "1 秒   (デフォルト 10s → 10 倍高速)"),
        ("OSPF dead-interval",      "3 秒   (デフォルト 40s → 13 倍高速)"),
        ("BFD transmit/receive",    "50 ms, detect-multiplier=3 → 150ms 検出"),
        ("SRGB",                    "16000 〜 23999"),
        ("CR1〜3 リンク帯域",        "各 100 Mbps (HTB で制限)"),
        ("WRR 比率",                "AF41:AF42:AF43 = 4:2:1 → 57M : 28M : 14M Mbps"),
        ("netem 追加遅延",           "AF42: +10ms / AF43: +40ms"),
        ("TX レート",               "Tx1/2/3 各 500 Mbps (UDP, iperf3)"),
        ("計測時間",                 "60 秒 / シナリオ (障害: t=20s down, t=40s up)"),
        ("実測収束時間",             "failure_reroute: 全クラス ≈ 1.0 秒"),
    ]
    for sname, sval in settings:
        ax.text(0.02, y, f"• {sname}", fontsize=9, color=CGR,
                va="top", transform=ax.transAxes)
        ax.text(0.42, y, sval, fontsize=9, color=CB, fontweight="bold",
                va="top", transform=ax.transAxes)
        y -= 0.026

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

# ═══════════════════════════════════════════════════════════════════════════
# メイン
# ═══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print(f"PDF 生成中: {OUT}")
    with PdfPages(OUT) as pdf:
        page_title(pdf);       print("  [1/11] タイトル")
        page_ch1(pdf);         print("  [2/11] 第1章 IPルーティング基礎")
        page_ch2_adj(pdf);     print("  [3/11] 第2章 OSPF① 隣接関係")
        page_ch2_lsa(pdf);     print("  [4/11] 第2章 OSPF② LSA/SPF")
        page_ch3_intro(pdf);   print("  [5/11] 第3章 MPLS① 基礎")
        page_ch3_forward(pdf); print("  [6/11] 第3章 MPLS② 転送動作")
        page_ch4_intro(pdf);   print("  [7/11] 第4章 SR① 概要")
        page_ch4_srgb(pdf);    print("  [8/11] 第4章 SR② SRGB/転送")
        page_ch5_lab(pdf);     print("  [9/11] 第5章 ラボ動作①")
        page_ch5_failure(pdf); print(" [10/11] 第5章 ラボ動作② 障害・収束")
        page_glossary(pdf);    print(" [11/11] 用語集")
    print(f"\n完了: {OUT}")
