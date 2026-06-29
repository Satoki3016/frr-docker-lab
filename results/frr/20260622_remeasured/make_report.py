#!/usr/bin/env python3
"""障害診断レポート PDF 生成スクリプト"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
import os

# ── フォント登録（CID: 日本語組み込みフォント）──────────────────────────
pdfmetrics.registerFont(UnicodeCIDFont('HeiseiKakuGo-W5'))
pdfmetrics.registerFont(UnicodeCIDFont('HeiseiMin-W3'))

# ── スタイル定義 ──────────────────────────────────────────────────────────
BASE = "HeiseiKakuGo-W5"
BOLD = "HeiseiKakuGo-W5"

def style(name, **kw):
    kw.setdefault("fontName", BASE)
    s = ParagraphStyle(name, **kw)
    return s

H1   = style("H1",   fontSize=18, fontName=BOLD, spaceAfter=4*mm,
             textColor=colors.HexColor("#1a3a6b"))
H2   = style("H2",   fontSize=13, fontName=BOLD, spaceAfter=2*mm,
             spaceBefore=5*mm, textColor=colors.HexColor("#1a5276"),
             borderPad=1*mm)
H3   = style("H3",   fontSize=11, fontName=BOLD, spaceAfter=1.5*mm,
             spaceBefore=3*mm, textColor=colors.HexColor("#154360"))
BODY = style("Body", fontSize=9.5, leading=16, spaceAfter=1.5*mm)
MONO = style("Mono", fontSize=8.5, fontName=BASE, leading=14,
             backColor=colors.HexColor("#f0f0f0"), leftIndent=5*mm,
             spaceAfter=2*mm)
SUB  = style("Sub",  fontSize=8.5, leading=14, textColor=colors.HexColor("#555"))
WARN = style("Warn", fontSize=9.5, leading=16, spaceAfter=1.5*mm,
             textColor=colors.HexColor("#922b21"))
OK   = style("OK",   fontSize=9.5, leading=16, spaceAfter=1.5*mm,
             textColor=colors.HexColor("#1e8449"))

def hline(color="#cccccc", thickness=0.5):
    return HRFlowable(width="100%", thickness=thickness,
                      color=colors.HexColor(color), spaceAfter=2*mm)

# ── ドキュメント構築 ──────────────────────────────────────────────────────
OUT = os.path.join(os.path.dirname(__file__),
                   "frr_debug_report_20260622.pdf")
doc = SimpleDocTemplate(
    OUT, pagesize=A4,
    leftMargin=20*mm, rightMargin=20*mm,
    topMargin=18*mm, bottomMargin=18*mm,
    title="FRR OSPF-SR DiffServ-TE 障害診断レポート",
    author="frr-docker-lab",
)

story = []

# ════════════════════════════════════════════════════════════════
# 表紙ヘッダ
# ════════════════════════════════════════════════════════════════
story.append(Spacer(1, 8*mm))
story.append(Paragraph("FRR OSPF-SR + DiffServ-TE", H1))
story.append(Paragraph("大型パケット全損失 — 障害診断レポート", H1))
story.append(hline("#1a3a6b", 1.5))
story.append(Paragraph("作成日: 2026-06-22　　実験環境: frr-docker-lab (Linux/Docker/veth)", SUB))
story.append(Spacer(1, 4*mm))

# ════════════════════════════════════════════════════════════════
# 1. 概要
# ════════════════════════════════════════════════════════════════
story.append(Paragraph("1. 問題の概要", H2))
story.append(hline())

story.append(Paragraph(
    "FRR OSPF-SR + DiffServ-TE WRR 4:2:1 ラボ実験において、iperf3 (UDP, 8950 byte) "
    "を送信したところ <b>受信側バイト数が常に 0</b> となり通信が成立しなかった。"
    "小パケット (100 byte, 1450 byte) は正常に到達するが、<b>2048 byte を超えるパケットが"
    "すべて廃棄</b>されていた。", BODY))

story.append(Paragraph("■ 症状一覧", H3))
data = [
    ["テスト内容", "パケットサイズ", "結果"],
    ["ping (小)", "100 byte", "✓ 0% ロス"],
    ["ping (中)", "1400 / 1450 byte", "✓ 0% ロス"],
    ["ping (大)", "8900 byte", "✗ 100% ロス"],
    ["iperf3 UDP", "8950 byte", "✗ 受信 0 bytes"],
    ["iperf3 control", "TCP (< 1500 byte)", "✓ 接続確立 (後に切断)"],
]
t = Table(data, colWidths=[70*mm, 50*mm, 45*mm])
t.setStyle(TableStyle([
    ("BACKGROUND",  (0,0), (-1,0), colors.HexColor("#1a3a6b")),
    ("TEXTCOLOR",   (0,0), (-1,0), colors.white),
    ("FONTNAME",    (0,0), (-1,0), BOLD),
    ("FONTNAME",    (0,1), (-1,-1), BASE),
    ("FONTSIZE",    (0,0), (-1,-1), 9),
    ("ROWBACKGROUNDS", (0,1), (-1,-1),
     [colors.HexColor("#f7f9fc"), colors.white]),
    ("GRID",        (0,0), (-1,-1), 0.4, colors.HexColor("#cccccc")),
    ("TOPPADDING",  (0,0), (-1,-1), 3),
    ("BOTTOMPADDING",(0,0),(-1,-1), 3),
    ("LEFTPADDING", (0,0), (-1,-1), 4),
]))
story.append(t)
story.append(Spacer(1, 3*mm))

# ════════════════════════════════════════════════════════════════
# 2. 診断プロセス
# ════════════════════════════════════════════════════════════════
story.append(Paragraph("2. 診断プロセス", H2))
story.append(hline())

story.append(Paragraph("① MTU 確認（疑い → 否定）", H3))
story.append(Paragraph(
    "最初に veth ペア全区間の MTU を確認した。"
    "tx1-leri, leri-tx1, leri-cr1, cr1-leri, lere-cr1 いずれも <b>MTU=9000</b> と設定済みで、"
    "MTU 不足は原因でなかった。", BODY))

story.append(Paragraph("② PMTU キャッシュ確認（疑い → 否定）", H3))
story.append(Paragraph(
    "Tx1 のルートキャッシュ (<code>ip route show cache</code>) を確認・フラッシュしたが、"
    "大型 ping の失敗は継続した。", BODY))

story.append(Paragraph("③ iptables カウンタ確認（重要な手がかり）", H3))
story.append(Paragraph(
    "LER_Ingress の <b>iptables mangle PREROUTING DSCPMARK チェーン</b>の "
    "ICMP ルールカウンタを確認したところ、小パケット 10 個は計上されているが、"
    "8900 byte ping 5 個は<b>カウンタに反映されていなかった</b>。", BODY))
story.append(Paragraph(
    "→ 大型パケットは iptables に到達する前に廃棄されている、と判断。", WARN))

story.append(Paragraph("④ tc ingress フィルタの統計確認（原因特定）", H3))
story.append(Paragraph(
    "LER_Ingress の leri-tx1 に設定されたイングレスポリサーの統計を確認:", BODY))
story.append(Paragraph(
    "tc -s filter show dev leri-tx1 parent ffff:", MONO))
story.append(Paragraph(
    "police 0x1 rate 42857Mbit burst 53571427b  <b>mtu 2Kb</b>  action drop  overhead 0b", MONO))
story.append(Paragraph(
    "Sent 2359420147079 bytes 264655002 pkts  <b>(dropped 262773428, overlimits 262773428)</b>", MONO))
story.append(Paragraph(
    "「<b>mtu 2Kb</b>」という値と「262,773,428 パケット廃棄」が確認された。"
    "送信総パケット数 264,655,002 のうち 262,773,428 個（約 99.3%）が廃棄されていた。", WARN))

story.append(Paragraph("⑤ ポリサー一時削除による確認（根本原因の確定）", H3))
story.append(Paragraph(
    "leri-tx1 のイングレス qdisc を削除 (<code>tc qdisc del dev leri-tx1 ingress</code>) "
    "した直後に 8900 byte ping を送信:", BODY))
story.append(Paragraph(
    "3 packets transmitted, 3 received, <b>0% packet loss</b>  rtt avg 0.120 ms", MONO))
story.append(Paragraph("→ 大型パケットが即座に疎通。根本原因はイングレスポリサーの mtu 設定と確定。", OK))

# ════════════════════════════════════════════════════════════════
# 3. 根本原因
# ════════════════════════════════════════════════════════════════
story.append(Paragraph("3. 根本原因", H2))
story.append(hline())

# 根本原因1
story.append(Paragraph("【主因】tc police のデフォルト mtu = 2Kb", H3))
story.append(Paragraph(
    "Linux の <b>tc police アクション</b>は、<code>mtu</code> パラメータを省略すると"
    "デフォルトで <b>2048 byte (2 Kb)</b> が適用される。"
    "この mtu は「正常パケット（conforming パケット）の最大サイズ」として機能し、"
    "<b>mtu を超えるパケットはレート制限とは無関係に「overlimit」として DROP される。</b>", BODY))

story.append(Paragraph("問題のある設定コード (frr_dscp_te.sh 修正前):", SUB))
story.append(Paragraph(
    "tc filter add dev \"$dev\" parent ffff: protocol all \\<br/>"
    "&nbsp;&nbsp;&nbsp;&nbsp;u32 match u32 0 0 \\<br/>"
    "&nbsp;&nbsp;&nbsp;&nbsp;police rate \"${rate}kbit\" burst \"${burst}b\"  <b>drop flowid :1</b>",
    MONO))

story.append(Paragraph("影響:", SUB))
data2 = [
    ["パケットサイズ", "tc police の判定", "結果"],
    ["≤ 2048 byte", "conforming（正常）", "✓ 通過"],
    ["> 2048 byte", "overlimit（超過）として誤判定", "✗ DROP"],
    ["8950 byte UDP (iperf3)", "overlimit", "✗ DROP — 受信 0 bytes"],
    ["8900 byte ICMP (ping -s 8900)", "overlimit", "✗ DROP — 100% ロス"],
]
t2 = Table(data2, colWidths=[55*mm, 70*mm, 42*mm])
t2.setStyle(TableStyle([
    ("BACKGROUND",  (0,0), (-1,0), colors.HexColor("#7b241c")),
    ("TEXTCOLOR",   (0,0), (-1,0), colors.white),
    ("FONTNAME",    (0,0), (-1,0), BOLD),
    ("FONTNAME",    (0,1), (-1,-1), BASE),
    ("FONTSIZE",    (0,0), (-1,-1), 9),
    ("ROWBACKGROUNDS", (0,1), (-1,-1),
     [colors.HexColor("#fdedec"), colors.white]),
    ("GRID",        (0,0), (-1,-1), 0.4, colors.HexColor("#cccccc")),
    ("TOPPADDING",  (0,0), (-1,-1), 3),
    ("BOTTOMPADDING",(0,0),(-1,-1), 3),
    ("LEFTPADDING", (0,0), (-1,-1), 4),
]))
story.append(t2)
story.append(Spacer(1, 3*mm))

story.append(Paragraph(
    "なぜ気づきにくかったか: バースト量 (53 MB) と転送レート (42.8 Gbps) は十分に大きく、"
    "「レート超過でドロップされている」という直感的な解釈には至りにくい。"
    "また tc の man ページに mtu のデフォルト値が明示されていないため見落としやすい。", SUB))

# 根本原因2
story.append(Paragraph("【副因】NETEM_LIMIT_HI = 30（過小なキュー長）", H3))
story.append(Paragraph(
    "lab_config.sh の <code>NETEM_LIMIT_HI</code> がデフォルト 30 パケットに設定されていた。"
    "AF41 クラスは 25G×4/7 ≈ 14.3 Gbps、8950 byte パケットで約 200 Kpps に相当する。"
    "netem キュー長 30 パケットでは数十マイクロ秒分しかバッファできず、"
    "バースト時にパケットロスが発生しやすい状態だった。", BODY))
story.append(Paragraph(
    "※ ただし、主因（tc police mtu 2Kb）の修正前は大型パケットがポリサーで全廃棄されていたため、"
    "この副因の影響は顕在化していなかった。", SUB))

# ════════════════════════════════════════════════════════════════
# 4. 修正内容
# ════════════════════════════════════════════════════════════════
story.append(Paragraph("4. 実施した修正", H2))
story.append(hline())

story.append(Paragraph("修正① — tc police に mtu 9000 を追加（主修正）", H3))
story.append(Paragraph("対象ファイル: scripts/frr_dscp_te.sh  — Ingress policing セクション", SUB))

data3 = [
    ["", "コード"],
    ["修正前", "police rate \"${rate}kbit\" burst \"${burst}b\" drop flowid :1"],
    ["修正後", "police rate \"${rate}kbit\" burst \"${burst}b\" mtu 9000 drop flowid :1"],
]
t3 = Table(data3, colWidths=[18*mm, 150*mm])
t3.setStyle(TableStyle([
    ("BACKGROUND",  (0,0), (-1,0), colors.HexColor("#1a3a6b")),
    ("TEXTCOLOR",   (0,0), (-1,0), colors.white),
    ("FONTNAME",    (0,0), (-1,0), BOLD),
    ("FONTNAME",    (0,1), (-1,-1), BASE),
    ("FONTSIZE",    (0,0), (-1,-1), 8.5),
    ("BACKGROUND",  (0,1), (-1,1), colors.HexColor("#fdedec")),
    ("BACKGROUND",  (0,2), (-1,2), colors.HexColor("#eafaf1")),
    ("GRID",        (0,0), (-1,-1), 0.4, colors.HexColor("#cccccc")),
    ("TOPPADDING",  (0,0), (-1,-1), 4),
    ("BOTTOMPADDING",(0,0),(-1,-1), 4),
    ("LEFTPADDING", (0,0), (-1,-1), 4),
]))
story.append(t3)
story.append(Spacer(1, 2*mm))
story.append(Paragraph(
    "この修正により、tc police が 9000 byte 以下のパケットを conforming として扱い、"
    "レート範囲内であれば正常に通過させるようになった。"
    "適用対象は leri-tx1/tx2/tx3 の 3 インタフェース（全 Tx→LER_Ingress 入力）。", BODY))

story.append(Paragraph("修正② — NETEM_LIMIT_HI を 30 → 100000 に拡大（副修正）", H3))
story.append(Paragraph("対象ファイル: scripts/lab_config.sh", SUB))

data4 = [
    ["", "設定値", "根拠"],
    ["修正前", "NETEM_LIMIT_HI=30", "デフォルト値（設定根拠なし）"],
    ["修正後", "NETEM_LIMIT_HI=100000", "25G×4/7≈200Kpps, バースト吸収に十分な余裕"],
]
t4 = Table(data4, colWidths=[18*mm, 50*mm, 100*mm])
t4.setStyle(TableStyle([
    ("BACKGROUND",  (0,0), (-1,0), colors.HexColor("#1a3a6b")),
    ("TEXTCOLOR",   (0,0), (-1,0), colors.white),
    ("FONTNAME",    (0,0), (-1,0), BOLD),
    ("FONTNAME",    (0,1), (-1,-1), BASE),
    ("FONTSIZE",    (0,0), (-1,-1), 8.5),
    ("BACKGROUND",  (0,1), (-1,1), colors.HexColor("#fdedec")),
    ("BACKGROUND",  (0,2), (-1,2), colors.HexColor("#eafaf1")),
    ("GRID",        (0,0), (-1,-1), 0.4, colors.HexColor("#cccccc")),
    ("TOPPADDING",  (0,0), (-1,-1), 4),
    ("BOTTOMPADDING",(0,0),(-1,-1), 4),
    ("LEFTPADDING", (0,0), (-1,-1), 4),
]))
story.append(t4)

# ════════════════════════════════════════════════════════════════
# 5. 修正後の結果
# ════════════════════════════════════════════════════════════════
story.append(Paragraph("5. 修正後の計測結果（2026-06-22）", H2))
story.append(hline())

story.append(Paragraph("■ frr_normal — WRR 4:2:1 正常動作確認", H3))
story.append(Paragraph(
    "全クラスが CR1 経由で 25 Gbps を WRR 比率どおりに分配:", BODY))

data5 = [
    ["クラス", "実測スループット", "理論値 (25G×N/7)", "誤差"],
    ["AF41 (高優先, 重み4)", "14.28 Gbps", "14.29 Gbps", "< 0.1%"],
    ["AF42 (中優先, 重み2)", "7.14 Gbps",  "7.14 Gbps",  "< 0.1%"],
    ["AF43 (低優先, 重み1)", "3.57 Gbps",  "3.57 Gbps",  "< 0.1%"],
    ["合計",                "24.99 Gbps", "25.00 Gbps", "< 0.1%"],
]
t5 = Table(data5, colWidths=[60*mm, 45*mm, 48*mm, 16*mm])
t5.setStyle(TableStyle([
    ("BACKGROUND",  (0,0), (-1,0), colors.HexColor("#1a5276")),
    ("TEXTCOLOR",   (0,0), (-1,0), colors.white),
    ("FONTNAME",    (0,0), (-1,0), BOLD),
    ("FONTNAME",    (0,1), (-1,-1), BASE),
    ("FONTSIZE",    (0,0), (-1,-1), 9),
    ("ROWBACKGROUNDS", (0,1), (-1,-1),
     [colors.HexColor("#eaf4fb"), colors.white]),
    ("BACKGROUND",  (0,4), (-1,4), colors.HexColor("#d5f5e3")),
    ("FONTNAME",    (0,4), (-1,4), BOLD),
    ("GRID",        (0,0), (-1,-1), 0.4, colors.HexColor("#aaaaaa")),
    ("TOPPADDING",  (0,0), (-1,-1), 3),
    ("BOTTOMPADDING",(0,0),(-1,-1), 3),
    ("LEFTPADDING", (0,0), (-1,-1), 4),
]))
story.append(t5)
story.append(Spacer(1, 3*mm))

story.append(Paragraph("■ frr_failure / frr_failure_reroute — 障害時自動迂回の効果", H3))

data6 = [
    ["シナリオ", "障害発生", "通信断時間", "復旧方式"],
    ["frr_failure\n（迂回なし）",
     "t=20s CR1 DOWN\n(t=40s CR1 UP)",
     "約 21 秒\n(t=21s ～ t=41s)",
     "CR1 復旧まで全停止\n（unreachable フォールバック）"],
    ["frr_failure_reroute\n（OSPF-SR 動的迂回）",
     "t=20s CR1 DOWN\n(t=40s CR1 UP)",
     "約 1〜2 秒\n(t=21s のみ完全断)",
     "frr_te_monitor が CR2 へ切替\n（BFD 150ms + OSPF 収束監視）"],
]
t6 = Table(data6, colWidths=[45*mm, 45*mm, 38*mm, 42*mm])
t6.setStyle(TableStyle([
    ("BACKGROUND",  (0,0), (-1,0), colors.HexColor("#1a5276")),
    ("TEXTCOLOR",   (0,0), (-1,0), colors.white),
    ("FONTNAME",    (0,0), (-1,0), BOLD),
    ("FONTNAME",    (0,1), (-1,-1), BASE),
    ("FONTSIZE",    (0,0), (-1,-1), 8.5),
    ("BACKGROUND",  (0,1), (-1,1), colors.HexColor("#fdedec")),
    ("BACKGROUND",  (0,2), (-1,2), colors.HexColor("#eafaf1")),
    ("GRID",        (0,0), (-1,-1), 0.4, colors.HexColor("#aaaaaa")),
    ("TOPPADDING",  (0,0), (-1,-1), 4),
    ("BOTTOMPADDING",(0,0),(-1,-1), 4),
    ("LEFTPADDING", (0,0), (-1,-1), 4),
    ("VALIGN",      (0,0), (-1,-1), "MIDDLE"),
]))
story.append(t6)
story.append(Spacer(1, 2*mm))
story.append(Paragraph(
    "OSPF-SR + frr_te_monitor（BFD高速検知 + operstate監視）により、"
    "CR1 障害時の通信断を <b>21 秒 → 1〜2 秒</b> に短縮（約 10〜20 倍の回復速度改善）。", OK))

# ════════════════════════════════════════════════════════════════
# 6. まとめ
# ════════════════════════════════════════════════════════════════
story.append(Paragraph("6. まとめ", H2))
story.append(hline())

story.append(Paragraph(
    "本実験で通信が成立しなかった直接原因は、<b>tc police アクションのデフォルト mtu 値 "
    "(2048 byte = 2 Kb)</b> によってジャンボフレーム相当のパケットが全廃棄されていたことである。"
    "この問題は iptables のカウンタが増加しないという観測から「パケットが iptables に到達する前に"
    "廃棄されている」と絞り込み、tc ingress フィルタの統計 (mtu 2Kb、廃棄 262M パケット) "
    "により確定した。", BODY))

story.append(Paragraph(
    "修正は frr_dscp_te.sh の tc filter コマンドに <code>mtu 9000</code> を追加するだけであったが、"
    "この 1 パラメータの省略が実験全体を無効化していた。"
    "tc のデフォルト値が man ページに明記されていないことが見落としの主因であり、"
    "ジャンボフレームを使用する環境では <b>tc police に必ず mtu をジャンボフレーム以上に"
    "明示指定する</b>ことが必要である。", BODY))

story.append(Spacer(1, 4*mm))
story.append(hline("#1a3a6b", 1))
story.append(Paragraph(
    "実験環境: frr-docker-lab-main2 / FRR 8.4 OSPF-SR / Linux veth / Docker / "
    "DiffServ HTB WRR 4:2:1 / CR=25Gbps", SUB))

# ── 生成 ─────────────────────────────────────────────────────────────────
doc.build(story)
print(f"PDF generated: {OUT}")
