#!/usr/bin/env python3
"""ラボ構築課題レポート PDF 生成"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

FONT_PATH = "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf"
FONT_BOLD  = "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf"

pdfmetrics.registerFont(TTFont("NotoSans",     FONT_PATH))
pdfmetrics.registerFont(TTFont("NotoSansBold", FONT_BOLD))

OUT = os.path.join(os.path.dirname(__file__), "lab_report.pdf")

W, H = A4
MARGIN = 20 * mm

# ── スタイル定義 ──────────────────────────────────────────────
def sty(name, **kw):
    base = dict(fontName="NotoSans", fontSize=10, leading=16,
                textColor=colors.black)
    base.update(kw)
    return ParagraphStyle(name, **base)

S_TITLE   = sty("title",  fontName="NotoSansBold", fontSize=20, leading=28,
                 spaceAfter=6, alignment=1)
S_SUBTITLE= sty("sub",    fontName="NotoSans",     fontSize=11, leading=16,
                 spaceAfter=16, alignment=1, textColor=colors.HexColor("#555555"))
S_H1      = sty("h1",     fontName="NotoSansBold", fontSize=14, leading=20,
                 spaceBefore=14, spaceAfter=4,
                 textColor=colors.HexColor("#1a3a6b"))
S_H2      = sty("h2",     fontName="NotoSansBold", fontSize=11, leading=16,
                 spaceBefore=8,  spaceAfter=2,
                 textColor=colors.HexColor("#2c5f9e"))
S_BODY    = sty("body",   spaceAfter=4)
S_CODE    = sty("code",   fontName="Courier",      fontSize=8.5, leading=13,
                 leftIndent=8, spaceAfter=4,
                 textColor=colors.HexColor("#1a1a1a"))
S_BULLET  = sty("bullet", leftIndent=12, spaceAfter=3,
                 bulletIndent=4)
S_CAPTION = sty("caption",fontSize=8, textColor=colors.HexColor("#666666"),
                 alignment=1, spaceAfter=8)

def h1(text):  return Paragraph(text, S_H1)
def h2(text):  return Paragraph(text, S_H2)
def p(text):   return Paragraph(text, S_BODY)
def code(text):return Paragraph(text.replace("\n","<br/>").replace(" ","&nbsp;"), S_CODE)
def bullet(text): return Paragraph(f"・{text}", S_BULLET)
def sp(n=4):   return Spacer(1, n*mm)
def hr():      return HRFlowable(width="100%", thickness=0.5,
                                  color=colors.HexColor("#cccccc"), spaceAfter=4)

S_CELL     = sty("cell",   fontSize=9, leading=14)
S_CELL_HDR = sty("cellhdr",fontName="NotoSansBold", fontSize=9, leading=14)

def table(data, col_widths, header=True):
    def wrap(text, is_header=False):
        if isinstance(text, str):
            return Paragraph(text, S_CELL_HDR if is_header else S_CELL)
        return text
    wrapped = []
    for i, row in enumerate(data):
        wrapped.append([wrap(cell, is_header=(i == 0)) for cell in row])
    t = Table(wrapped, colWidths=col_widths)
    style = [
        ("VALIGN",      (0,0), (-1,-1), "TOP"),
        ("GRID",        (0,0), (-1,-1), 0.5, colors.HexColor("#bbbbbb")),
        ("BACKGROUND",  (0,0), (-1,0),  colors.HexColor("#dce6f7")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1),
         [colors.white, colors.HexColor("#f5f8ff")]),
        ("TOPPADDING",  (0,0), (-1,-1), 4),
        ("BOTTOMPADDING",(0,0),(-1,-1), 4),
        ("LEFTPADDING", (0,0), (-1,-1), 5),
        ("RIGHTPADDING",(0,0), (-1,-1), 5),
    ]
    t.setStyle(TableStyle(style))
    return t

# ── コンテンツ ────────────────────────────────────────────────
story = []

# 表紙
story += [
    sp(20),
    Paragraph("MPLS QoS ラボ構築", S_TITLE),
    Paragraph("課題・原因・対処・現状レポート", S_SUBTITLE),
    sp(4),
    hr(),
    sp(2),
]

# ── 問題1 ──
story += [
    h1("問題1：SONiC スイッチで MPLS が動かなかった（最大の問題）"),
    h2("何が起きたか"),
    p("SONiC スイッチに MPLS の設定を入れて ping を送っても、パケットが全く届かなかった。"
      "tcpdump で監視しても受信 0 パケット。設定は正しいのに応答なし。"),
    sp(2),
    h2("原因"),
    p("SONiC に搭載されている Broadcom のスイッチチップが、パケットを"
      "「Linux カーネルに渡さず、チップ内部で直接転送してしまう」仕組みになっていた。"),
    sp(1),
    table(
        [["経路", "動作"],
         ["通常の Linux", "パケット → Linux カーネル → MPLS 処理 → 転送"],
         ["SONiC の実態", "パケット → チップが直接転送 → Linux には届かない"]],
        [40*mm, 110*mm]
    ),
    sp(3),
    h2("試みたこと（全て失敗）"),
    table(
        [["試した方法", "失敗した理由"],
         ["Ethernet ポートを別の namespace に移動",
          "SONiC のドライバが root namespace 以外にパケットを届けられない"],
         ["ブリッジ＋veth で namespace に引き込む",
          "同じくドライバの制約でパケットが届かない"],
         ["config interface ip add でスイッチに IP を設定し veth で接続",
          "ARP・自分宛通信は成功したが、通過パケットはチップが横取りした"]],
        [55*mm, 95*mm]
    ),
    sp(3),
    h2("結論と解決策"),
    p("SONiC では MPLS・QoS は原理的に不可能と判断。"),
    p("<b>→ SONiC は L2 スイッチ（VLAN ブリッジ）として使うだけにして、"
      "MPLS/QoS の処理は全て virttrx（サーバー）側の Linux namespace で行う</b>構成に切り替えた。"),
    sp(2), hr(),
]

# ── 問題2 ──
story += [
    h1("問題2：macvtap が物理 NIC を占有していた"),
    h2("何が起きたか"),
    p("Tx3 用に使いたかった NIC（enp179s0f0np0）を namespace に移動しようとしたが失敗し、"
      "Tx3_ns が作れなかった。"),
    sp(2),
    h2("原因"),
    p("VM（ubuntu2004virt1）が macvtap という仮想インターフェース経由でその NIC を使用中だった。"),
    sp(2),
    h2("解決策"),
    p("VM からNIC をホットデタッチして解放した："),
    code("virsh detach-interface ubuntu2004virt1 direct --mac 52:54:00:20:bf:12 --live"),
    sp(2), hr(),
]

# ── 問題3 ──
story += [
    h1("問題3：QoS（優先制御）が効いていなかった"),
    h2("何が起きたか"),
    p("高優先・中優先・低優先のトラフィックを設定したのに、全て同じ扱いになっていた。"),
    sp(2),
    h2("原因"),
    p("TC（トラフィックコントロール）がパケットをクラスに振り分けるには「fwmark（優先度の印）」が必要。"
      "しかし iptables は DSCP を付けるだけで、fwmark を設定していなかった。"
      "結果として全パケットが「印なし」のままデフォルト＝最低優先クラスに流れ込んでいた。"),
    sp(2),
    h2("解決策"),
    p("iptables に DSCP → fwmark の変換ルールを追加した："),
    code("iptables -t mangle -A PREROUTING -m dscp --dscp-class AF41 -j MARK --set-mark 41\n"
         "iptables -t mangle -A PREROUTING -m dscp --dscp-class AF42 -j MARK --set-mark 42\n"
         "iptables -t mangle -A PREROUTING -m dscp --dscp-class AF43 -j MARK --set-mark 43"),
    sp(2), hr(),
]

# ── 問題4 ──
story += [
    h1("問題4：スクリプトの設定がバラバラだった"),
    h2("何が起きたか"),
    p("measure.sh（計測スクリプト）を実行したら途中で止まってしまった。"),
    sp(2),
    h2("原因"),
    p("スクリプトを作り直した際に namespace の名前（LER_Ingress と LER_Ingress_ns）や"
      "IP アドレス（10.2.x.x と 10.20.x.x）が統一されておらず、"
      "別々のスクリプトがバラバラな名前で同じ namespace を呼ぼうとしていた。"),
    sp(2),
    h2("解決策"),
    p("関係する全スクリプトの名前と IP を統一した："),
    table(
        [["ファイル", "主な修正内容"],
         ["measure.sh",          "namespace 名・IP の修正、グラフ自動生成を追加"],
         ["60_rsvp_te.sh",       "全 namespace 名・IP を修正"],
         ["rsvp_monitor.sh",     "namespace 名・デバイス名・IP を修正"],
         ["throughput_monitor.sh","namespace 名・デバイス名を修正"],
         ["virttrx_tc.sh",       "デバイス名を修正"]],
        [60*mm, 90*mm]
    ),
    sp(2), hr(),
]

# ── 問題5 ──
story += [
    h1("問題5：物理ケーブルが足りなかった"),
    h2("何が起きたか"),
    p("Tx 側と Rx 側を全部物理ケーブルで繋ごうとしたが NIC が足りなかった。"),
    sp(2),
    h2("原因"),
    p("物理接続 1 本あたり NIC が両端で 1 枚ずつ計 2 枚必要。"
      "Tx3 本＋Rx3 本を全部物理にするには <b>12 枚必要</b>なのに、"
      "virttrx の NIC は <b>6 枚だけ</b>。"),
    sp(2),
    h2("解決策"),
    p("3 案を検討し、<b>「Tx 側 3 本を全部物理化、Rx 側は仮想（veth）」</b>を採用した。"),
    p("Tx 側が物理であれば「実際のネットワークからトラフィックが入ってくる」"
      "という最も重要な部分が再現でき、研究目的として十分。"),
    sp(2),
    table(
        [["NIC", "役割"],
         ["enp23s0f0np0",   "Tx1_ns（高優先 AF41 送信側）"],
         ["enp23s0f1np1",   "LER_Ingress_ns（Tx1 受信側）"],
         ["enp179s0f0np0",  "Tx2_ns（中優先 AF42 送信側）"],
         ["enp179s0f1np1",  "LER_Ingress_ns（Tx2 受信側）"],
         ["enp5s0f0",       "Tx3_ns（低優先 AF43 送信側）"],
         ["enp5s0f1",       "LER_Ingress_ns（Tx3 受信側）"]],
        [55*mm, 95*mm]
    ),
    sp(2), hr(),
]

# ── 現在の構成 ──
story += [
    h1("現在の構成"),
    h2("ネットワーク構成図"),
    table(
        [["区間", "接続方式", "備考"],
         ["Tx1_ns ↔ LER_Ingress_ns", "物理（VLAN10）", "SONiC スイッチ経由"],
         ["Tx2_ns ↔ LER_Ingress_ns", "物理（VLAN11）", "SONiC スイッチ経由"],
         ["Tx3_ns ↔ LER_Ingress_ns", "物理（VLAN12）", "SONiC スイッチ経由"],
         ["LER_Ingress_ns ↔ CoreRouter1/2/3_ns", "仮想（veth）", "virttrx 内部"],
         ["CoreRouter1/2/3_ns ↔ LER_Egress_ns",  "仮想（veth）", "virttrx 内部"],
         ["LER_Egress_ns ↔ Rx1/2/3_ns",          "仮想（veth）", "virttrx 内部"]],
        [65*mm, 40*mm, 45*mm]
    ),
    sp(3),
    h2("動作状況"),
    bullet("MPLS ラベルスイッチング（ingress → transit swap → egress pop）が正常動作"),
    bullet("DiffServ QoS：DSCP マーキング＋WRR 4:2:1 優先制御が正常動作"),
    bullet("measure.sh 一発で計測からグラフ生成まで自動完了"),
    bullet("normal / failure / failure_rsvp の 3 シナリオが実行可能"),
    sp(3),
    h2("計測コマンド"),
    code("sudo bash scripts/measure.sh 60 normal\n"
         "sudo bash scripts/measure.sh 60 failure\n"
         "sudo bash scripts/measure.sh 60 failure_rsvp"),
]

# ── PDF 生成 ──────────────────────────────────────────────────
doc = SimpleDocTemplate(
    OUT, pagesize=A4,
    leftMargin=MARGIN, rightMargin=MARGIN,
    topMargin=MARGIN,  bottomMargin=MARGIN,
    title="MPLS QoS ラボ構築 課題レポート",
)
doc.build(story)
print(f"PDF 生成完了: {OUT}")
