#!/usr/bin/env python3
"""
generate_progress_report.py
R8研究進捗報告 (2026.07.01) PDF 生成
参考: R8研究進捗報告(2026.06.03).pdf のスタイルを踏襲
"""

from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, PageBreak, KeepTogether, HRFlowable
)
from reportlab.platypus.flowables import Flowable
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

# ── 日本語フォント ─────────────────────────────────────────────────────────────
pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))
pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
SERIF = "HeiseiMin-W3"
SANS  = "HeiseiKakuGo-W5"

# ── カラー ────────────────────────────────────────────────────────────────────
C_ORANGE  = colors.HexColor("#E07B00")
C_ORANGE2 = colors.HexColor("#F4A623")
C_BLACK   = colors.HexColor("#1A1A1A")
C_GRAY    = colors.HexColor("#666666")
C_LGRAY   = colors.HexColor("#F5F5F5")
C_MGRAY   = colors.HexColor("#E0E0E0")
C_DGRAY   = colors.HexColor("#444444")
C_BLUE    = colors.HexColor("#2563EB")
C_TBLUE   = colors.HexColor("#EFF6FF")
C_WHITE   = colors.white
C_HL      = colors.HexColor("#FFF3CD")   # ハイライト（黄）
C_REDBG   = colors.HexColor("#FEE2E2")
C_GREENBG = colors.HexColor("#D1FAE5")

PAGE_W, PAGE_H = A4
MARGIN_L = 22 * mm
MARGIN_R = 22 * mm
MARGIN_T = 20 * mm
MARGIN_B = 18 * mm
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R

# ── パス ──────────────────────────────────────────────────────────────────────
BASE    = Path("/home/kannolab/デスクトップ/Ichikawa_projects/frr-docker-lab-main2")
FIG_DIR = BASE / "results/frr/20260630_25G_veth4/figures"
OUT     = BASE / "results/frr/R8研究進捗報告(2026.07.01).pdf"

# ── スタイル ──────────────────────────────────────────────────────────────────
def S(name, **kw):
    kw.setdefault("fontName", SANS)
    kw.setdefault("textColor", C_BLACK)
    return ParagraphStyle(name, **kw)

STYLES = {
    # 大タイトル
    "doc_title": S("doc_title", fontSize=28, leading=36, spaceBefore=4, spaceAfter=6,
                   fontName=SANS, textColor=C_BLACK),
    # セクション見出し「• Background」
    "sec_head": S("sec_head", fontSize=16, leading=22, spaceBefore=14, spaceAfter=4,
                  fontName=SANS, textColor=C_BLACK),
    # サブセクション「▼ 実験構成」
    "sub_head": S("sub_head", fontSize=11.5, leading=16, spaceBefore=10, spaceAfter=3,
                  fontName=SANS, textColor=C_BLACK),
    # 小見出し「• 原因」
    "item_head": S("item_head", fontSize=10.5, leading=15, spaceBefore=6, spaceAfter=2,
                   fontName=SANS, textColor=C_BLACK),
    # 本文
    "body": S("body", fontSize=10, leading=16.5, spaceAfter=7,
              alignment=TA_JUSTIFY, fontName=SANS),
    # 本文（左揃え）
    "body_l": S("body_l", fontSize=10, leading=16.5, spaceAfter=5,
                fontName=SANS),
    # インデント付き本文
    "body_ind": S("body_ind", fontSize=10, leading=16.5, spaceAfter=5,
                  leftIndent=10, fontName=SANS),
    # さらにインデント
    "body_ind2": S("body_ind2", fontSize=10, leading=16.5, spaceAfter=4,
                   leftIndent=20, fontName=SANS),
    # コード
    "code": S("code", fontSize=9, leading=14, spaceAfter=3,
              fontName="Courier", leftIndent=14, textColor=C_DGRAY),
    # キャプション
    "caption": S("caption", fontSize=8.5, leading=12, spaceAfter=6,
                 alignment=TA_CENTER, textColor=C_GRAY),
    # メタ表内
    "meta_label": S("meta_label", fontSize=9, leading=13, textColor=C_GRAY,
                    fontName=SANS),
    "meta_val":   S("meta_val", fontSize=10, leading=14, textColor=C_BLACK,
                    fontName=SANS),
    "meta_hl":    S("meta_hl", fontSize=10, leading=14, textColor=C_BLACK,
                    fontName=SANS, backColor=colors.HexColor("#FDE68A")),
    # フッター
    "footer": S("footer", fontSize=8, textColor=C_GRAY, fontName=SANS),
    # 強調付き本文（太字は同フォントで代替）
    "body_b": S("body_b", fontSize=10, leading=16.5, spaceAfter=7,
                fontName=SANS, textColor=C_BLACK),
}

# ── オレンジ棒グラフアイコン ──────────────────────────────────────────────────
class BarIcon(Flowable):
    def __init__(self, size=28):
        self.size = size
        self.width = size
        self.height = size

    def draw(self):
        c = self.canv
        s = self.size
        c.setFillColor(C_ORANGE)
        c.rect(0, 0, s, s, fill=1, stroke=0)
        c.setFillColor(C_WHITE)
        bar_w = s * 0.18
        gap   = s * 0.07
        base  = s * 0.15
        heights = [s*0.35, s*0.55, s*0.70]
        x = s * 0.12
        for h in heights:
            c.rect(x, base, bar_w, h, fill=1, stroke=0)
            x += bar_w + gap

# ── ページ番号フッター ─────────────────────────────────────────────────────────
DOC_TITLE_STR = "R8研究進捗報告(2026.07.01)"

def add_footer(canv, doc):
    canv.saveState()
    canv.setFont(SANS, 8)
    canv.setFillColor(C_GRAY)
    # 左下：文書タイトル
    canv.drawString(MARGIN_L, 10 * mm, DOC_TITLE_STR)
    # 右下：ページ番号
    canv.drawRightString(PAGE_W - MARGIN_R, 10 * mm, str(doc.page))
    # 上部オレンジライン
    canv.setStrokeColor(C_ORANGE)
    canv.setLineWidth(3)
    canv.line(MARGIN_L, PAGE_H - 12 * mm, PAGE_W - MARGIN_R, PAGE_H - 12 * mm)
    canv.restoreState()

# ── ヘルパー ──────────────────────────────────────────────────────────────────
def p(text, style="body"):
    return Paragraph(text, STYLES[style])

def sp(h=4):
    return Spacer(1, h * mm)

def hr(color=C_MGRAY, thickness=0.5):
    return HRFlowable(width="100%", thickness=thickness, color=color,
                      spaceBefore=2, spaceAfter=2)

def fig(name, w_mm=140, caption=None):
    path = FIG_DIR / f"{name}.png"
    if not path.exists():
        return []
    w = w_mm * mm
    img = Image(str(path), width=w, height=w * 0.62)
    items = [sp(2), img]
    if caption:
        items.append(p(caption, "caption"))
    items.append(sp(2))
    return items

def highlight_box(text, bg=C_HL, border=C_ORANGE2):
    """ハイライトボックス（課題・解決策）"""
    inner = Table(
        [[Paragraph(text, STYLES["body_l"])]],
        colWidths=[CONTENT_W - 10*mm]
    )
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0,0),(-1,-1), bg),
        ("BOX",        (0,0),(-1,-1), 1, border),
        ("TOPPADDING",    (0,0),(-1,-1), 6),
        ("BOTTOMPADDING", (0,0),(-1,-1), 6),
        ("LEFTPADDING",   (0,0),(-1,-1), 8),
        ("RIGHTPADDING",  (0,0),(-1,-1), 8),
    ]))
    return inner

def code_box(lines):
    """コマンドブロック"""
    text = "<br/>".join(lines)
    inner = Table(
        [[Paragraph(text, STYLES["code"])]],
        colWidths=[CONTENT_W - 8*mm]
    )
    inner.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), C_LGRAY),
        ("BOX",           (0,0),(-1,-1), 0.5, C_MGRAY),
        ("TOPPADDING",    (0,0),(-1,-1), 6),
        ("BOTTOMPADDING", (0,0),(-1,-1), 6),
        ("LEFTPADDING",   (0,0),(-1,-1), 10),
        ("RIGHTPADDING",  (0,0),(-1,-1), 8),
    ]))
    return inner

def tbl(data, col_widths, header_rows=1):
    style = TableStyle([
        ("BACKGROUND", (0,0), (-1, header_rows-1), C_DGRAY),
        ("TEXTCOLOR",  (0,0), (-1, header_rows-1), C_WHITE),
        ("FONTNAME",   (0,0), (-1,-1), SANS),
        ("FONTSIZE",   (0,0), (-1,-1), 9),
        ("ALIGN",      (0,0), (-1,-1), "CENTER"),
        ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0,header_rows),(-1,-1), [C_WHITE, C_LGRAY]),
        ("GRID",       (0,0), (-1,-1), 0.4, C_MGRAY),
        ("TOPPADDING",    (0,0),(-1,-1), 4),
        ("BOTTOMPADDING", (0,0),(-1,-1), 4),
        ("LEFTPADDING",   (0,0),(-1,-1), 6),
        ("RIGHTPADDING",  (0,0),(-1,-1), 6),
    ])
    t = Table(data, colWidths=[c*mm for c in col_widths])
    t.setStyle(style)
    return t

# ── ドキュメント構築 ──────────────────────────────────────────────────────────
def build():
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=A4,
        leftMargin=MARGIN_L, rightMargin=MARGIN_R,
        topMargin=MARGIN_T + 6*mm, bottomMargin=MARGIN_B + 6*mm,
        title=DOC_TITLE_STR,
        author="市川慧騎",
    )

    story = []

    # ════════════════════════════════════════════════════════════════════════
    # 表紙メタデータ
    # ════════════════════════════════════════════════════════════════════════
    story += [
        BarIcon(30),
        sp(3),
        p("R8研究進捗報告(2026.07.01)", "doc_title"),
        sp(4),
    ]

    # メタデータ表
    meta = [
        ["報告者",       "市川慧騎"],
        ["研究題目",     "固定無線と有線ネットワークを統合制御するネットワーク制御技術の研究"],
        ["作成日時",     "2026年7月1日"],
        ["最終更新日時", "2026年7月1日"],
        ["研究トピック", "ネットワーク制御"],
        ["研究者名",     "市川慧騎"],
    ]
    meta_data = []
    for label, val in meta:
        lp = Paragraph(label, STYLES["meta_label"])
        if label == "研究題目":
            vp = Paragraph(val, STYLES["meta_hl"])
        else:
            vp = Paragraph(val, STYLES["meta_val"])
        meta_data.append([lp, vp])

    meta_tbl = Table(meta_data, colWidths=[22*mm, CONTENT_W - 22*mm])
    meta_tbl.setStyle(TableStyle([
        ("FONTNAME",   (0,0),(-1,-1), SANS),
        ("FONTSIZE",   (0,0),(-1,-1), 9),
        ("VALIGN",     (0,0),(-1,-1), "MIDDLE"),
        ("GRID",       (0,0),(-1,-1), 0.4, C_MGRAY),
        ("BACKGROUND", (0,0),(0,-1), C_LGRAY),
        ("TOPPADDING",    (0,0),(-1,-1), 5),
        ("BOTTOMPADDING", (0,0),(-1,-1), 5),
        ("LEFTPADDING",   (0,0),(-1,-1), 6),
        ("RIGHTPADDING",  (0,0),(-1,-1), 6),
        # 研究題目行をハイライト
        ("BACKGROUND", (1,1),(1,1), colors.HexColor("#FDE68A")),
    ]))
    story += [meta_tbl, sp(10)]

    # ════════════════════════════════════════════════════════════════════════
    # Background, Purpose
    # ════════════════════════════════════════════════════════════════════════
    story += [
        p("• Background , Purpose", "sec_head"),
        hr(C_MGRAY),
        sp(2),
        p("▼ 背景、課題、解決方法", "sub_head"),
        p("背景１：有線無線融合ネットワーク", "item_head"),
    ]

    story += [
        p("2030年代にBeyond5G時代を迎え、超高速、大規模接続、超低遅延、高信頼性が求められる。また、世界のデータトラフィックは急速に増加しており、月間のモバイルデータトラフィックは2025年の195EBから2030年には2倍以上となる430EBにまで増加すると予想されている。"),
        p("このように増加するグローバルトラフィックに対して長距離にわたる信号伝送部分は有線接続、スマホなどの移動体には無線接続などのそれぞれの利点を活かす通信が求められている。"),
        p("しかし、全てのデバイスを有線で接続するのはコストや労力の観点から現実的に不可能である。また全てのデバイスを無線で接続することも限られた無線資源の状況から不可能であり、大気や雨などの環境による影響を受けて安定さにも課題が残っている。"),
        p("このことから各々の利点を活かし、欠点を補える有線無線融合ネットワークが求められる。"),
        sp(4),
        p("背景２：Quality of Service (QoS)", "item_head"),
        p("動画配信・音楽配信・電子書籍など多様なトラフィックはそれぞれ特性が異なり、リアルタイムの動画配信は遅延が少ないことが重要な一方で、電子書籍はリアルタイム性よりもデータに欠損が無く送られなければならないため帯域幅の大きさが重要となる。"),
        p("これらの特徴を無視して通信をすると映像から音が遅れて聞こえたり、ファイルデータが欠損して送られてしまう可能性がある。各種類のトラフィックに対して安定した通信を確保するためにはサービス品質を担保するQoS制御が必要となる。"),
        sp(4),
        p("課題", "item_head"),
        p("以上の背景から問題点として「①全てのデバイスの有線接続化は不可能②無線資源は限定的で安定さにも課題③多様で膨大なトラフィックに対する優先制御が必要」の3つを挙げる。この3つの問題点を解決するための課題として「①安定した有線無線融合ネットワークの構築②多様で膨大なトラフィックに対するQoS制御」の2つを設定する。"),
        sp(4),
        p("解決方法", "item_head"),
        p("①安定した有線無線融合ネットワークの構築→MPLS：ラベルによる明示的な経路制御、各種サービスのサポート", "body_ind"),
        p("②QoS制御→DiffServ：優先度制御　MPLS：優先度に基づくルーティング制御", "body_ind"),
        sp(4),
        p("▼ 原理", "sub_head"),
        p("• DiffServ", "item_head"),
        p("パケットの優先度ごとにルーターが処理する方式。6ビットのDSCPフィールドに優先度を設定（マーキング）し、優先度に基づいた帯域割り当て（スケジューリング）を行う。本実験ではAF41（高優先）・AF42（中優先）・AF43（低優先）の3クラスを使用する。", "body_ind"),
        p("• OSPF-SR (Segment Routing)", "item_head"),
        p("FRR 8.4が実装するOSPF拡張。各ノードにSegment ID（SID）を割り当て、ラベルスタックで明示的な転送経路を指定する。リンク障害を検知してOSPF再収束後に自動的に迂回経路へ切り替える。", "body_ind"),
    ]

    # ════════════════════════════════════════════════════════════════════════
    # Keywords
    # ════════════════════════════════════════════════════════════════════════
    story += [
        sp(6),
        p("• Keywords", "sec_head"),
        hr(C_MGRAY),
        sp(2),
        p("Beyond5G"),
        p("ネットワーク"),
        p("有線無線融合"),
        p("QoS"),
        p("DiffServ-TE"),
        p("OSPF-SR"),
        p("MPLS"),
        p("HTB（Hierarchical Token Bucket）"),
    ]

    # ════════════════════════════════════════════════════════════════════════
    # What was revealed
    # ════════════════════════════════════════════════════════════════════════
    story += [
        PageBreak(),
        p("• What was revealed", "sec_head"),
        hr(C_MGRAY),
        sp(2),
    ]

    # ── やろうとしたこと ─────────────────────────────────────────────────────
    story += [
        p("やろうとしたこと：veth仮想環境でDiffServ-TE × OSPF-SR を実証", "sub_head"),
        p("Linux上のDockerコンテナをveth（仮想イーサネット）で接続し、同一ホスト上でMPLS + OSPF-SR（FRR 8.4）の動作を検証する。HTB（SP＋WRR）によるQoS制御と、リンク障害時のOSPF自動リルーティングを3シナリオで比較計測する。"),
    ]

    # ── 実験構成 ─────────────────────────────────────────────────────────────
    story += [
        p("▼ 実験構成", "sub_head"),
        p("• トポロジー", "item_head"),
        code_box([
            "Tx1 ─[AF41 UDP:1000 8950B]─┐",
            "Tx2 ─[AF42 UDP:2000 8950B]─┤─[LER_Ingress]─┬─CR1─┬─[LER_Egress]─┬─Rx1",
            "Tx3 ─[AF43 UDP:3000 8950B]─┘               ├─CR2─┤              ├─Rx2",
            "                                             └─CR3─┘              └─Rx3",
            "全リンク：Linux veth ペア（帯域制限なし、HTBで25G相当に設定）",
        ]),
        sp(3),
    ]

    param_data = [
        ["パラメータ", "値", "備考"],
        ["CRリンク帯域 (HTB root rate)", "25 Gbps", "各CR×3本"],
        ["AF41 送信レート", "3 Gbps × 4 stream = 12 Gbps", "SP保護帯域(14.3G)以下"],
        ["AF42 送信レート", "15 Gbps × 4 stream = 60 Gbps", "WRR割当(7.1G)の8.4倍"],
        ["AF43 送信レート", "15 Gbps × 4 stream = 60 Gbps", "WRR割当(3.6G)の16.8倍"],
        ["総送信量", "132 Gbps", "リンク帯域の5.3倍"],
        ["パケット長", "8950 B (UDP)", "ジャンボフレーム想定"],
        ["計測時間", "60秒/シナリオ", "t=5–55sを解析対象"],
        ["HTB WRR比", "AF41:AF42:AF43 = 4:2:1", "quantum 36KB:18KB:9KB"],
    ]
    story += [
        p("• 実験パラメータ", "item_head"),
        tbl(param_data, [52, 56, 58]),
        sp(3),
    ]

    scenario_data = [
        ["シナリオ", "内容", "CR1障害", "OSPF-SR迂回"],
        ["normal",          "全3リンクECMP+HTB QoS",           "なし",        "なし"],
        ["failure",         "t=20sにCR1ダウン、t=41s復旧",     "t=20–41s",   "なし"],
        ["failure_reroute", "failureと同条件、OSPF収束後に迂回", "t=20–41s",   "あり(t≈21s)"],
    ]
    story += [
        p("• 計測シナリオ", "item_head"),
        tbl(scenario_data, [38, 62, 30, 36]),
        sp(6),
    ]

    # ── 問題1 ────────────────────────────────────────────────────────────────
    story += [
        p("▼ 問題１：計測スクリプトが「SW2 計測完了」出力後にハングする", "sub_head"),
        p("• 原因", "item_head"),
    ]
    story += [
        p("SW2で実行するスクリプト（physical2_frr_measure_sw2.sh）のスループットモニターをバックグラウンドサブシェルで起動する際、stdout/stderrは<font name='Courier'>/dev/null</font>へリダイレクトしていたが、<b>stdin（fd 0）をSSHセッションのパイプから引き継いだまま</b>だった。"),
        p("SSHサーバーはサブシェルがstdinを保持している限り接続を切れないため、sw2.shがすべての処理を終えて最終メッセージを出力した後もSSHセッションが生き続け、PC側のall.shがSW2_PIDの終了を永遠に待ち続けた。"),
        sp(3),
        p("• 想定していた動作", "item_head"),
        p("バックグラウンド起動直後にメインシェルが終了 → SSHセッションが閉じる → SW2_PIDが消える → all.shが次のステップへ進む", "body_ind"),
        p("• 実際の動作", "item_head"),
        p("バックグラウンドサブシェルがstdinを掴み続ける → SSHサーバーが接続を維持 → SW2_PIDが生き続ける → all.shがSW2完了待ちループから抜け出せない", "body_ind"),
        p("• 試したこと", "item_head"),
        p("①stdout/stderrのリダイレクト（<font name='Courier'>> /dev/null 2>&1 &</font>）→ stdinは残るため未解決", "body_ind"),
        p("②kill + wait の追加 → サブシェル本体は終了するが子プロセス（sleep 1等）が一瞬stdinを保持するため、タイミングによりハングが残った", "body_ind"),
        p("• 結論と解決策", "item_head"),
        highlight_box(
            "サブシェル起動を <font name='Courier'>() &lt; /dev/null &gt; /dev/null 2&gt;&amp;1 &amp;</font> に変更。"
            "stdinも/dev/nullに向けることでSSHパイプのfd継承を完全に遮断する。"
            "さらにクリーンアップを SIGTERM → 0.5s → SIGKILL + pkill -9 -P の3段階に強化。"
        ),
        sp(6),
    ]

    # ── 問題2 ────────────────────────────────────────────────────────────────
    story += [
        p("▼ 問題２：物理環境でHTBレートがvethの値（25G）のまま適用される", "sub_head"),
        p("• 原因", "item_head"),
        p("all.shから <font name='Courier'>frr_dscp_te.sh</font> をSSH経由で実行する際、<font name='Courier'>LAB_MODE=physical</font> を渡していなかった。"),
        p("lab_config.sh は <font name='Courier'>$LAB_MODE</font> の値によって veth用（25G）か physical用（100M）のパラメータを切り替えるが、LAB_MODEが未設定のためvethのデフォルト値が使われ続けた。"),
        sp(3),
        p("• 想定していた動作", "item_head"),
        p("LAB_MODE=physical → lab_config.sh が lab_config_physical.sh をsource → CR帯域100M、TX 500Mで設定", "body_ind"),
        p("• 実際の動作", "item_head"),
        p("LAB_MODEが未設定 → lab_config.sh が lab_config_veth.sh をsource → CR帯域25G、TX 15Gで物理スイッチに設定 → 意図しない帯域制限が掛かる", "body_ind"),
        p("• 結論と解決策", "item_head"),
        highlight_box(
            "all.sh内の呼び出しを<br/>"
            "<font name='Courier'>$SSH \"$SW1\" \"sudo LAB_MODE=physical bash /home/kannolab/scripts/frr_dscp_te.sh\"</font><br/>"
            "に修正。環境変数をssh経由で明示的に渡すことで正しいパラメータが適用される。"
        ),
        sp(6),
    ]

    # ── 実験方法、結果 ────────────────────────────────────────────────────────
    story += [
        PageBreak(),
        p("▼ 実験方法、結果", "sub_head"),
        p("• 実行コマンド", "item_head"),
        code_box([
            "# veth環境（同一ホスト上のDockerコンテナ）",
            "sudo bash scripts/frr_all_up.sh",
            "sudo bash scripts/frr_measure.sh 60 normal",
            "sudo bash scripts/frr_measure.sh 60 failure",
            "sudo bash scripts/frr_measure.sh 60 failure_reroute",
        ]),
        sp(4),
        p("• 基本方針", "item_head"),
        p("前回の進捗と条件を揃えることを意識した。normal・failure・failure_rerouteの3シナリオで計測。failure・failure_reroute では t=20s〜t=41s においてLER_Ingressと CR1 の間で障害（リンクダウン）を発生させた。"),
        p("• 理論値との比較（normalシナリオ、定常区間 t=5–55s）", "item_head"),
    ]

    theory_data = [
        ["クラス", "HTB割当", "理論値 (Gbps)", "実測値 (Gbps)", "誤差 (%)"],
        ["AF41", "4/7 × 25G (SP)", "14.286", "14.285 ± 0.009", "0.007"],
        ["AF42", "2/7 × 25G (WRR)", "7.143",  "7.140 ± 0.005", "0.042"],
        ["AF43", "1/7 × 25G (WRR)", "3.571",  "3.570 ± 0.002", "0.028"],
    ]
    story += [
        tbl(theory_data, [22, 40, 36, 46, 22]),
        p("理論値と実測値の一致は最大誤差0.07%以内。HTB SP+WRR 4:2:1の設計が正確に実現されていることを確認した。", "caption"),
        sp(4),
    ]

    story += fig("compare_throughput", 155,
                 "図1：3シナリオのクラス別スループット時系列（Rx側受信量）")

    story += [
        p("• スループット時系列（図1）の読み方", "item_head"),
        p("normalでは計測開始直後から定常値に達し、3クラスとも変動が極めて小さい（σ＜0.01Gbps）。failureではt=21sから21秒間、全クラスのスループットが0に落ちる。OSPFが迂回を設定していないためIP層でunreachableによりドロップされる。failure_rerouteではt=21sに約1秒の中断後、OSPFが収束して定常値へ回復する。"),
        sp(4),
    ]

    story += fig("compare_packetloss", 130,
                 "図2：シナリオ別クラス別パケットロス率")

    story += [
        sp(2),
        p("• 片道遅延（OWD）", "item_head"),
    ]

    owd_data = [
        ["クラス", "OWD中央値 (ms)", "対AF41比"],
        ["AF41 (SP)", "5.21", "1.0×"],
        ["AF42 (WRR 2)", "20.27", "3.89×"],
        ["AF43 (WRR 1)", "80.71", "15.49×"],
    ]
    story += [
        tbl(owd_data, [44, 44, 44]),
        p("HTBのquantum比（4:2:1）に起因するキュー待機時間の差がOWDに現れている。AF43はAF41の約15.5倍の遅延を示し、低優先クラスに対するbufferbloat効果を定量化した。", "caption"),
        sp(4),
    ]

    story += fig("compare_rtt", 130,
                 "図3：シナリオ別クラス別OWD（中央値・四分位範囲）")

    story += [
        PageBreak(),
        p("• TC クラスドロップ", "item_head"),
        p("leri-cr1インタフェースのHTBクラス別ドロップを確認した。"),
    ]

    drop_data = [
        ["クラス", "normal (pkt/s)", "failure (pkt/s)", "failure_reroute (pkt/s)"],
        ["AF41", "50,207", "32,101", "54,498"],
        ["AF42", "67,541", "39,322", "67,057"],
        ["AF43", "33,771", "19,640", "33,485"],
        ["AF42/AF43比", "2.00", "2.00", "2.00"],
    ]
    story += [
        tbl(drop_data, [32, 46, 46, 46]),
        p("AF42:AF43のドロップ比が2:1でありWRRの動作を直接確認。failureのtc_drop値が低いのは、障害期間中にIP層でdropされHTBに届かないため。", "caption"),
        sp(4),
    ]

    story += fig("compare_drop_location", 150,
                 "図4：シナリオ別HTBクラスドロップ数（leri-cr1出口）")

    # ── 3シナリオ比較まとめ ───────────────────────────────────────────────────
    story += [
        p("• 3シナリオ比較まとめ", "item_head"),
    ]

    summary_data = [
        ["指標", "normal", "failure", "failure_reroute"],
        ["AF41 スループット (Gbps)", "14.285", "8.394 (障害期間含む)", "14.208"],
        ["AF42 スループット (Gbps)", "7.140",  "4.199",                "7.112"],
        ["AF43 スループット (Gbps)", "3.570",  "2.099",                "3.558"],
        ["AF41 OWD中央値 (ms)",     "5.21",   "5.14",                 "5.13"],
        ["AF42 OWD中央値 (ms)",     "20.27",  "20.25",                "20.25"],
        ["AF43 OWD中央値 (ms)",     "80.71",  "80.69",                "80.69"],
        ["障害中断時間 (s)",         "—",      "21",                   "≈1"],
        ["正常比スループット回復率", "100%",   "—",                    "98.7%"],
    ]
    story += [
        tbl(summary_data, [56, 38, 46, 46]),
        sp(6),
    ]

    # ── failure_reroute の仕組み ─────────────────────────────────────────────
    story += [
        p("• failure_reroute の仕組み", "item_head"),
        p("①frr_te_monitor.sh が <font name='Courier'>ip monitor link</font>（netlink）でCR1リンクダウンイベントを検知", "body_ind"),
        p("②OSPFの収束を待機（vtysh で route確認ループ）", "body_ind"),
        p("③<font name='Courier'>ip route replace</font> でCR2への迂回ルートをatomicに書き換え", "body_ind"),
        p("t=21sのスループット低下（AF41: 10.73 Gbps）は切り替え遷移中の1秒サンプルを反映。実際の中断はサブ秒オーダーと推定される。", "body_ind"),
        sp(6),
    ]

    # ── 制限事項 ─────────────────────────────────────────────────────────────
    story += [
        p("▼ 制限事項・今後の課題", "sub_head"),
        p("①<b>veth送信帯域の上限（CPUボトルネック）</b>：Linux vethの転送はsoftirqコンテキストで処理されるため、AF42の総送信量（60 Gbps）を実際にはsoftirq限界（≈25 Gbps）で頭打ちになる場合がある。物理NIC環境では同様のボトルネックは発生しない。", "body_ind"),
        p("②<b>OWD絶対値の精度</b>：vethのsoftirq遅延＋PythonのclockオーバーヘッドがAF41に5 ms程度加算される。物理環境より大幅に大きいため、クラス間の相対比のみが有意な比較指標となる。", "body_ind"),
        p("③<b>再現性</b>：各シナリオ1回の計測。物理2SW環境での追試によりveth特有の制約の影響を分離する必要がある。", "body_ind"),
        p("④<b>次ステップ</b>：物理2SW環境（SONiC + MMFケーブル）でのスループット・OWD・障害リルーティング実証。", "body_ind"),
    ]

    # ── Git管理 ─────────────────────────────────────────────────────────────
    story += [
        sp(4),
        p("▼ 実行コマンド（記録）", "sub_head"),
        code_box([
            "git add -A",
            'git commit -m "20260630: veth 25G 3シナリオ計測完了"',
            "git push origin main",
        ]),
    ]

    doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)
    print(f"[ok] PDF生成完了: {OUT}")

if __name__ == "__main__":
    build()
