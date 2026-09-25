#!/usr/bin/env python3
"""RADWIN TerraNet 無線導入から計測までの記録を PDF 化する。

本セッション (2026-09-04 〜 09-11) で実施した作業の記録。
数値はすべて実測値であり、推定値には明示的にその旨を記す。
"""
from __future__ import annotations

from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

JP_FONT_PATH = "/usr/share/fonts/truetype/takao-gothic/TakaoGothic.ttf"
JP = "TakaoGothic"
pdfmetrics.registerFont(TTFont(JP, JP_FONT_PATH))

NAVY  = colors.HexColor("#183153")
BLUE  = colors.HexColor("#2878B5")
CYAN  = colors.HexColor("#DDEFF8")
GREY  = colors.HexColor("#666666")
RED   = colors.HexColor("#B03A2E")
GREEN = colors.HexColor("#1E8449")
LGREY = colors.HexColor("#F4F6F8")

ss = getSampleStyleSheet()
S = {
    "title":  ParagraphStyle("t",  parent=ss["Title"], fontName=JP, fontSize=20, leading=28, textColor=NAVY),
    "sub":    ParagraphStyle("s",  parent=ss["Normal"], fontName=JP, fontSize=10.5, leading=16,
                             alignment=TA_CENTER, textColor=GREY),
    "h1":     ParagraphStyle("h1", parent=ss["Heading1"], fontName=JP, fontSize=14, leading=20,
                             textColor=NAVY, spaceBefore=10, spaceAfter=6),
    "h2":     ParagraphStyle("h2", parent=ss["Heading2"], fontName=JP, fontSize=11.5, leading=17,
                             textColor=BLUE, spaceBefore=8, spaceAfter=4),
    "body":   ParagraphStyle("b",  parent=ss["Normal"], fontName=JP, fontSize=9.3, leading=15, spaceAfter=4),
    "cell":   ParagraphStyle("c",  parent=ss["Normal"], fontName=JP, fontSize=8.3, leading=12),
    "cellb":  ParagraphStyle("cb", parent=ss["Normal"], fontName=JP, fontSize=8.3, leading=12, textColor=NAVY),
    "mono":   ParagraphStyle("m",  parent=ss["Normal"], fontName="Courier", fontSize=7.8, leading=11),
    # 罫線文字 (U+2500台) は Courier に無く豆腐になるため、図には等幅の日本語フォントを使う
    "monojp": ParagraphStyle("mj", parent=ss["Normal"], fontName=JP, fontSize=7.0, leading=10.5),
    "note":   ParagraphStyle("n",  parent=ss["Normal"], fontName=JP, fontSize=8.5, leading=13, textColor=GREY),
}

def P(t, s="body"): return Paragraph(t, S[s])
def H1(t): return Paragraph(t, S["h1"])
def H2(t): return Paragraph(t, S["h2"])

def tbl(rows, widths, header=True, align_left_cols=()):
    data = [[Paragraph(c, S["cellb"] if (header and r == 0) else S["cell"]) if isinstance(c, str) else c
             for c in row] for r, row in enumerate(rows)]
    st = [("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#BCC6D0")),
          ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
          ("LEFTPADDING", (0,0), (-1,-1), 4), ("RIGHTPADDING", (0,0), (-1,-1), 4),
          ("TOPPADDING", (0,0), (-1,-1), 3), ("BOTTOMPADDING", (0,0), (-1,-1), 3)]
    if header:
        st += [("BACKGROUND", (0,0), (-1,0), CYAN)]
        st += [("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, LGREY])]
    else:
        st += [("ROWBACKGROUNDS", (0,0), (-1,-1), [colors.white, LGREY])]
    return Table(data, colWidths=widths, style=TableStyle(st), hAlign="LEFT")

def code(lines, style=None):
    # Courier は日本語も罫線も持たないため、非ASCIIを含む行があれば
    # 自動で等幅の日本語フォントに切り替える (豆腐の再発防止)
    if style is None:
        style = "monojp" if any(ord(c) > 0x7F for l in lines for c in l) else "mono"
    txt = "<br/>".join(l.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace(" ","&nbsp;")
                       for l in lines)
    t = Table([[Paragraph(txt, S[style])]], colWidths=[168*mm],
              style=TableStyle([("BACKGROUND",(0,0),(-1,-1),LGREY),
                                ("BOX",(0,0),(-1,-1),0.4,colors.HexColor("#BCC6D0")),
                                ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),
                                ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]),
              hAlign="LEFT")
    return t

def callout(title, body, color=RED):
    inner = [[Paragraph(f"<b>{title}</b>", ParagraphStyle("ct", parent=S["cell"], textColor=color))],
             [Paragraph(body, S["cell"])]]
    return Table(inner, colWidths=[168*mm],
                 style=TableStyle([("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#FCF3F2") if color==RED else colors.HexColor("#EFF8F1")),
                                   ("BOX",(0,0),(-1,-1),0.6,color),
                                   ("LEFTPADDING",(0,0),(-1,-1),7),("RIGHTPADDING",(0,0),(-1,-1),7),
                                   ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]),
                 hAlign="LEFT")

F = []
W = 168*mm

# ─── 表紙 ───────────────────────────────────────────────────────────
F += [Spacer(1, 38*mm),
      P("RADWIN TerraNet 60GHz 無線リンク導入記録", "title"),
      Spacer(1, 5*mm),
      P("有線経路の一つを実無線 2 ホップに置換し、DiffServ-TE と OSPF-SR の<br/>"
        "動作を実機で検証するまでの全工程", "sub"),
      Spacer(1, 12*mm)]
F += [tbl([["作業期間", "2026-09-04 〜 2026-09-11"],
           ["対象", "frr-docker-lab-main2 / LAB_MODE=c2 (3経路完全独立構成)"],
           ["導入機材", "RADWIN TerraNet V90 × 4 台 (JPN 版)"],
           ["到達点", "CR1 経路を 60GHz 無線 2 ホップに置換し、3 シナリオ計測を完了"],
           ["計測データ", "results/frr/radwin/setup/20260911_success_radwin_cr1_wireless/"]],
          [30*mm, 138*mm], header=False)]
F += [Spacer(1, 10*mm),
      P("本書の数値はすべて実測値である。推定・計算値にはその旨を明記した。", "note")]
F += [PageBreak()]

# ─── 1. 導入前後 ────────────────────────────────────────────────────
F += [H1("1. 何が変わったか")]
F += [P("従来、無線リンクの不安定さは netem による模擬であった。本作業では "
        "CR1 経路 (CoreRouter1 ↔ LER_Egress) の物理層を実機の 60GHz 無線に置き換えた。")]
F += [tbl([["", "導入前", "導入後"],
           ["CR1 経路の物理層", "10G 光ファイバ + ASIC", "<b>60GHz 無線 2 ホップ</b> (RADWIN V90 ×4)"],
           ["リンク容量の根拠", "設定値 9G (物理 10G の 90%)", "<b>無線の実測値</b>から決定"],
           ["無線の不安定さ", "netem で模擬", "実機の電波伝搬 (ただし障害注入は後述の制約あり)"],
           ["CR2 / CR3 経路", "10G 有線", "10G 有線 (変更なし)"]],
          [32*mm, 60*mm, 76*mm])]
F += [Spacer(1, 3*mm),
      P("CR2 / CR3 を有線のまま残したことで、<b>有線無線ハイブリッド網</b>となり、"
        "障害時に無線から有線へ迂回する挙動を同一計測内で観測できる構成になった。")]

# ─── 2. 最終構成 ────────────────────────────────────────────────────
F += [H1("2. 最終構成")]
F += [code([
 "                          ┌── CR1 ──[SW1:Eth18]=VLAN211=[SW1:Eth24]",
 "                          │                                  │ MMF",
 " Tx1 ─┐                   │                             KeepLINK-A",
 " Tx2 ─┼─ LER_Ingress ─────┤                                  │",
 " Tx3 ─┘                   │                              ODU-A(.31)",
 "                          │                                ))) 無線1 ch1 (((",
 "                          │                              ODU-B(.32)",
 "                          │                                  │ 中継 KeepLINK-B",
 "                          │                              ODU-C(.33)",
 "                          │                                ))) 無線2 ch4 (((",
 "                          │                              ODU-D(.34)",
 "                          │                                  │ KeepLINK-C / MMF",
 "                          │        [SW2:Eth11]=VLAN211=[SW2:Eth18]",
 "                          │             │                                    ┌─ Rx1",
 "                          ├── CR2 ──[SW1:Eth16]=VLAN212=[SW2:Eth7] ──┬── LER_Egress ─┼─ Rx2",
 "                          └── CR3 ──[SW1:Eth19]=VLAN213=[SW2:Eth5] ──┘        └─ Rx3",
])]
F += [Spacer(1, 3*mm)]
F += [tbl([["経路", "物理層", "CR_BW", "MTU", "VLAN"],
           ["CR1", "<b>60GHz 無線 2 ホップ</b>", "<b>900M</b>", "<b>7800</b>", "211"],
           ["CR2", "10G 有線", "9G", "9100", "212"],
           ["CR3", "10G 有線", "9G", "9100", "213"]],
          [16*mm, 62*mm, 24*mm, 22*mm, 44*mm])]
F += [Spacer(1, 3*mm),
      P("ODU は透過ブリッジであるため、IP・OSPF・MPLS の設定は一切変更していない。"
        "L3 から見れば「ケーブルが 1 本置き換わった」だけである。", "note")]

F += [Spacer(1, 4*mm), H2("2.1 デイジーチェーンがループしない理由")]
F += [P("ODU-A と ODU-B は別セグメント、ODU-C と ODU-D も別セグメントにある。"
        "ODU-B と ODU-C は中継セグメントを共有するが、無線の相手が異なるため全体が一直線になる。"
        "この構成に至るまでに 2 度ループを踏んだ (第 4 章)。")]
F += [PageBreak()]

# ─── 3. 機材と設定 ──────────────────────────────────────────────────
F += [H1("3. 機材と設定値")]
F += [H2("3.1 ODU 4 台")]
F += [tbl([["", "MAC", "管理IP", "役割", "SSID", "ch"],
           ["ODU-A", "c4:93:00:57:16:e9", "192.168.1.31", "PtP Access Point", "radwin-ptmp-a", "1"],
           ["ODU-B", "c4:93:00:57:7c:70", "192.168.1.32", "PtP Station", "radwin-ptmp-a", "—"],
           ["ODU-C", "c4:93:00:60:35:df", "192.168.1.33", "PtP Access Point", "(link2)", "4"],
           ["ODU-D", "c4:93:00:60:35:e2", "192.168.1.34", "PtP Station", "(link2)", "—"]],
          [16*mm, 38*mm, 26*mm, 34*mm, 32*mm, 22*mm])]
F += [Spacer(1, 2*mm),
      P("機種 RW-6P02-J260 (JPN 版・技適 R 006-0013B4)、FW v1.14.1 (r54664 / r54667)。"
        "チャネルを 1 (57.24–59.40 GHz) と 4 (63.72–65.88 GHz) に離すことで、"
        "2 本の無線が同時送信できる。同一チャネルなら帯域が半減していた。", "note")]

F += [H2("3.2 無線区間の実測性能")]
F += [tbl([["", "無線1 (A↔B)", "無線2 (C↔D)"],
           ["TX SpeedTest", "<b>2610 Mbps</b>", "<b>2438 Mbps</b>"],
           ["RX SpeedTest", "2404 Mbps", "2391 Mbps"],
           ["Signal", "-38 dBm", "-26 dBm"],
           ["MCS (Tx/Rx)", "12", "12 / 9"],
           ["PHY Datarate (Tx/Rx)", "4620 / 4620 Mbps", "4620 / 2502 Mbps"],
           ["SNR", "16", "16"],
           ["距離", "3 m", "2 m"],
           ["TX Retry", "ほぼ全て再送なし", "1–3 回再送が一部混在"]],
          [44*mm, 62*mm, 62*mm])]
F += [Spacer(1, 2*mm)]
F += [callout("PHY レートと実効スループットの差は正常",
  "4620 Mbps は MCS 12 の PHY シンボルレートであり、運べるデータ量ではない。実効は約 52–56%。"
  "主因は ① TDD (半二重。送受で時間を分け合う) ② MAC オーバーヘッド (プリアンブル・ACK・フレーム間隔) "
  "③ ビームフォーミング訓練の airtime 消費。V90 の公称は 2.0–2.3 Gbps (aggregate) であり、"
  "実測 2.4 Gbps はむしろ仕様以上。設定による改善余地はない (既に MCS 12・Full 2.16GHz チャネルで動作)。",
  GREEN)]
F += [Spacer(1, 2*mm),
      P("測定値が教科書どおりであることの裏付け: ODU が表示した Datarate 4620 / 2502 Mbps は、"
        "802.11ad の MCS 12 / MCS 9 の定義値と完全に一致する。", "note")]

F += [H2("3.3 有線部の実測")]
F += [tbl([["区間", "実測", "備考"],
           ["ODU 4 台の ETH0", "<b>2.5 Gbps full duplex</b>", "KeepLINK と 2.5G でネゴシエート済み"],
           ["SW1:Eth24 / SW2:Eth18", "10 Gbps", "OEM SFP-10G-SR (光・LC)"],
           ["経路 1 の通過 MTU", "<b>7899</b>", "二分探索で確定。ODU 設定上限 7900 とほぼ一致"],
           ["PC の処理限界", "1 経路あたり 約 9 Gbps", "3 経路同時では合計 約 10.7 Gbps で頭打ち"]],
          [42*mm, 46*mm, 80*mm])]
F += [Spacer(1, 2*mm),
      P("<b>銅が 2.5G で無線が 2.4G のため、経路上で最も細いのは無線区間である。</b>"
        "これは実験の前提そのものであり、実測で保証されたことに意味がある。"
        "仮に ETH0 が 1 Gbps であれば、実際には Ethernet の限界を測っていることになっていた。")]
F += [PageBreak()]

# ─── 4. 構築の経緯 ──────────────────────────────────────────────────
F += [H1("4. 構築の経緯 — 踏んだ問題と対処")]
F += [P("導入は一度で成功していない。以下は実際に遭遇した問題と、その切り分け方の記録である。"
        "同種の環境を再構築する際の参考となるよう、症状と決め手を併記した。")]

items = [
 ("4.1 L2 ループによるブロードキャストストーム (2 回)",
  "KeepLINK 1 台に ODU 2 台を収容したため、「有線経路 + 無線経路」で閉路が成立。"
  "<b>92,000 pps</b> のブロードキャストストームが発生した。CDP が正常の約 8000 倍の頻度で観測された。<br/>"
  "その後 4 台構成にした際、KeepLINK 2 台でも無線 2 本が並列になり <b>115,000 pps</b> に悪化。<br/>"
  "<b>対処:</b> KeepLINK 3 台でデイジーチェーン化し 0.3 pps まで低下。"
  "ODU 同士が有線セグメントを共有し、かつ無線でも繋がる構成を避けることが要点。"),
 ("4.2 V90 の出荷時デフォルトは AP モード",
  "2 台とも AP モードのままではリンクが張れない。Installation Guide には "
  "「V120 と V90 は Access Point モード、V40 は Station モード」と機種別に明記されているが、"
  "User Manual には「出荷時は Station」と書かれており記述が矛盾している。実機は前者が正しい。<br/>"
  "<b>対処:</b> 片方を Point-to-Point Access Point、もう片方を Point-to-Point Station に設定。"
  "Wireless Mode の変更には再起動が必要だが自動では再起動しない。"),
 ("4.3 LLDP では無線の疎通を判定できない",
  "LLDP は予約マルチキャストアドレス (01:80:c2:00:00:0e) を使うためブリッジが転送しない。"
  "したがって無線を越えない。過去に相手側 ODU が見えたのは、常に有線で同一セグメントにいたためであった。<br/>"
  "<b>対処:</b> 疎通確認は IP の ping で行う。スクリプト scripts/radwin_verify.sh を作成した。"),
 ("4.4 アンテナ距離 — 近すぎると繋がらない",
  "37dBi レンズ (RW-9437-5771) はビーム幅 4°×4°。遠方界の開始は 2D²/λ より約 3–8 m と見積もられ、"
  "数十 cm の距離ではビームが形成されない。RADWIN 自身もマニュアルに "
  "「ラボのような近距離では信号強度と反射により full performance が出にくい」と記載している。<br/>"
  "<b>対処:</b> レンズを外し Antenna Kit を Base unit only に統一、2–3 m 離して対向させた。"),
 ("4.5 macvtap passthru が NIC を占有 (症状が紛らわしい)",
  "経路 3 が疎通しなかった原因は、どの VM 定義にも属さない<b>孤児の macvtap0</b> "
  "(mode passthru、親は enp179s0f0np0) であった。passthru モードは親 NIC の受信経路を排他的に握るため、<br/>"
  "&nbsp;&nbsp;・<b>送信は通る</b> (スイッチの FDB に正しく MAC が学習される)<br/>"
  "&nbsp;&nbsp;・<b>受信だけ奪われる</b> (ping は 100% packet loss + errors)<br/>"
  "<b>切り分けの決め手はスイッチの FDB。</b>両スイッチが両端の MAC を正しいポートで学習しているのに "
  "ping が通らなければ、L2 配線ではなく PC 側で NIC が奪われていると判断できる。"),
 ("4.6 VLAN がリンクダウン中のポートと組になっていた",
  "経路 2 / 3 は本作業以前から不通であった。SW1 の VLAN 10 は Ethernet0 (up) と Ethernet2 (down)、"
  "VLAN 12 は Ethernet20 (up) と Ethernet22 (down) の組で、PC 側の生きたポート "
  "(Ethernet16 / Ethernet19) はどの VLAN にも属していなかった。SW2 に至っては該当 VLAN が存在しなかった。<br/>"
  "<b>対処:</b> VLAN 211 / 212 / 213 を新設し、両スイッチで config save により永続化した。"),
]
for t, b in items:
    F += [KeepTogether([H2(t), P(b)])]
F += [PageBreak()]

items2 = [
 ("4.7 rate_to_kbps の小数バグ — 設定値は整数 M 表記にすること",
  "scripts/ 配下の <b>10 ファイル</b>に rate_to_kbps() の実装があり、多くが非数字を全除去する "
  "(${r//[^0-9]/}) 方式である。この実装は <b>「2.1G」を「21G」と誤解釈</b>し、total_kbps が 10 倍になって "
  "HTB の保証帯域 (r_hi / r_me / r_lo) が壊れる。AF41 の保証がリンク全体となり SP 設計が崩壊するが、"
  "エラーは出ず数値だけ間違うため発見しにくい。<br/>"
  "<b>対処:</b> 設定値を「2100M」のような整数 M 表記にした。frr_dscp_te.sh の実装のみ小数対応に修正した。"),
 ("4.8 LAB_MODE が sudo で失われる",
  "run_all_scenarios.sh が内部で sudo bash frr_dscp_te.sh を呼んでおり、sudo の env_reset により "
  "LAB_MODE が捨てられていた。lab_config.sh は LAB_MODE 未設定だと veth 既定に落ち、"
  "CR_BW が全経路 9G になる。無線経路を 9G で整形すると <b>HTB がボトルネックにならず、"
  "無線側で無秩序にパケットが落ちる</b>ため QoS の実証が成立しない。<br/>"
  "<b>対処:</b> 内部 sudo を削除 (既に root で動作しているため不要)。"
  "起動時に LAB_MODE / CR_BW / TX_RATE / データグラム長を表示するようにした。"),
 ("4.9 iperf3 のデータグラム長が MTU を超過 (初回計測の失敗原因)",
  "初回計測では normal と failure のスループットがほぼゼロ、failure_reroute で有線へ迂回している間だけ "
  "8.04 Gbps が出るという症状になった。原因は frr_measure.sh の <b>-l 8950 固定</b>である。<br/>"
  "&nbsp;&nbsp;8950 (データ) + 8 (UDP) + 20 (IP) + 4 (MPLS ラベル) = <b>8982 バイト</b><br/>"
  "これが cr1-lere の MTU 7800 を超えるため送信できず破棄されていた。CR2/CR3 は MTU 9100 なので通る。<br/>"
  "<b>MPLS 透過性の問題ではない</b> (OSPF 隣接も ping も無線越しに成立していた)。<br/>"
  "<b>対処:</b> IPERF_DGRAM を lab_config に追加し、LAB_MODE=c2 では 7000 とした (7032 &lt; 7800)。"),
 ("4.10 netns 内のプロセスが物理 NIC を「迷子」にする",
  "iperf3 が netns 内に残っていると名前空間の参照が残り、ip netns del しても物理 NIC が "
  "root netns に戻らない (名前だけ消える)。次回実行時に「Cannot find device」となる。<br/>"
  "<b>対処:</b> クリーンアップ処理で netns 削除の<b>前に</b>プロセスを落とし、"
  "NIC が root に戻るまで待機するようにした (c2_fabric_test.sh / frr_setup.sh)。"),
]
for t, b in items2:
    F += [KeepTogether([H2(t), P(b)])]
F += [PageBreak()]

# ─── 5. 計測結果 ────────────────────────────────────────────────────
F += [H1("5. 計測結果")]
F += [P("実行: <font face='Courier' size='8'>sudo env LAB_MODE=c2 bash scripts/run_all_scenarios.sh 60 "
        "20260911_radwin_cr1_wireless_v2</font><br/>"
        "送信レートは 2G × 4 ストリーム × 3 クラス = 24G (設計上の不変前提により変更していない)。")]

F += [H2("5.1 normal — 無線経路 (CR1_BW = 900M)")]
F += [tbl([["クラス", "スループット", "損失", "リンク占有率", "片方向遅延 (OWD)"],
           ["AF41 (高)", "<b>0.861 Gbps</b>", "89%", "<b>95.7%</b>", "<b>67 ms</b>"],
           ["AF42 (中)", "0.026 Gbps", "ほぼ 100%", "2.9%", "4,385 ms"],
           ["AF43 (低)", "0.013 Gbps", "ほぼ 100%", "1.4%", "17,525 ms"],
           ["合計", "<b>0.900 Gbps</b>", "—", "100%", "—"]],
          [24*mm, 32*mm, 24*mm, 30*mm, 58*mm])]
F += [Spacer(1, 3*mm)]
F += [callout("① HTB が正確にボトルネックとして機能している",
  "合計 0.900 Gbps は設定値 CR1_BW = 900M と完全一致する。すなわちパケットが落ちている場所は "
  "無線の中ではなく<b>意図した HTB キューの中</b>である。「どこで落ちているかを制御できている」ことを意味し、"
  "測定の妥当性の根拠となる。", GREEN)]
F += [Spacer(1, 2*mm)]
F += [callout("② Strict Priority が効いている",
  "3 クラスの比は <b>66 : 2 : 1</b>。HTB の quantum 比は 4:2:1 であり、SP が効いていなければ 4:2:1 に近い値になる。"
  "66:2:1 という偏りは AF41 が借用帯域を最優先で獲得していることを示す。60 秒間 0.861 Gbps で安定しており、"
  "無線リンクが揺らいでいないことも確認できる。", GREEN)]

F += [Spacer(1, 3*mm), H2("5.2 OWD がキュー理論と一致する")]
F += [P("人工遅延 (netem) は一切入れていないが、AF41 と AF43 で <b>261 倍</b>の遅延差が生じた。"
        "この値は各クラスのキュー長 (pfifo) をサービスレートで割った値とほぼ一致する。")]
F += [tbl([["クラス", "pfifo 長", "サービスレート", "計算値", "実測値", "誤差"],
           ["AF41", "1000 pkt", "0.861 Gbps", "65.3 ms", "<b>67 ms</b>", "2.6%"],
           ["AF42", "2000 pkt", "0.026 Gbps", "4,327 ms", "<b>4,385 ms</b>", "1.3%"],
           ["AF43", "4000 pkt", "0.013 Gbps", "17,310 ms", "<b>17,525 ms</b>", "1.2%"]],
          [20*mm, 24*mm, 32*mm, 28*mm, 32*mm, 32*mm])]
F += [Spacer(1, 2*mm),
      P("計算式: パケット長 7032 バイト × pfifo 長 × 8 ÷ サービスレート。"
        "キューが飽和しているため <b>遅延 = バッファ深さ ÷ サービスレート</b> となる。"
        "3 クラスとも 3% 以内で一致しており、系が設計どおり動作していることの強い裏付けである。", "note")]

F += [Spacer(1, 3*mm), H2("5.3 failure / failure_reroute — 迂回の効果")]
F += [tbl([["", "断の長さ", "AF41 の損失", "迂回先"],
           ["failure (迂回なし)", "<b>約 20 秒</b>", "93%", "なし"],
           ["failure_reroute", "<b>約 2–3 秒</b>", "58%", "CR2 (有線 9G)"]],
          [42*mm, 32*mm, 34*mm, 60*mm])]
F += [Spacer(1, 2*mm)]
F += [code([
 "t=20   0.861 Gbps   ← 無線 CR1",
 "t=21   0.000        ← 障害",
 "t=23   0.974        ← 迂回開始",
 "t=24   8.055 Gbps   ← 有線 CR2 で完全復帰 (9.4 倍)",
])]
F += [Spacer(1, 2*mm),
      P("迂回先の有線経路でも合計 9.002 Gbps で CR2_BW = 9G と一致しており、HTB は迂回後も正しく機能している。"
        "<b>無線と有線の容量差が QoS に与える影響を、同一計測内で対比できる形になった。</b>")]
F += [PageBreak()]

# ─── 6. 考察 ────────────────────────────────────────────────────────
F += [H1("6. 考察")]
F += [H2("6.1 実無線でも DiffServ-TE は設計どおり動く")]
F += [P("netem で模擬していた区間を実物の 60GHz リンクに置き換えても、SP+WRR の挙動は変わらなかった。"
        "これは<b>過去の netem ベースの結果が妥当であったことの裏付け</b>にもなる。")]
F += [H2("6.2 容量が 1 桁違っても QoS の構造は保たれる")]
F += [tbl([["経路", "容量", "AF41", "AF42", "AF43"],
           ["無線 CR1", "0.9 Gbps", "<b>95.7%</b>", "2.9%", "1.4%"],
           ["有線 CR2", "9 Gbps", "<b>89.5%</b>", "7.0%", "3.5%"]],
          [28*mm, 28*mm, 36*mm, 36*mm, 40*mm])]
F += [Spacer(1, 2*mm),
      P("絶対値は 10 倍違うが<b>優先順位は不変</b>である。容量が減ると下位クラスがより強く締め出される、"
        "という違いが現れる。")]
F += [H2("6.3 routing が先、scheduling が後")]
F += [P("failure シナリオでは 3 クラスとも同時にゼロになった。最優先の AF41 も例外ではない。<br/>"
        "&nbsp;&nbsp;・<b>scheduling (DiffServ-TE)</b> は「使える経路の中で誰を優先するか」を決める<br/>"
        "&nbsp;&nbsp;・<b>routing (OSPF-SR)</b> は「そもそも使える経路を確保する」<br/>"
        "経路が無い間は、どれだけ優先度が高くても通信できない。"
        "<b>無線リンクは有線より切れやすいため、この役割分担は有線無線ハイブリッド網でこそ重要になる。</b>")]

# ─── 7. 限界 ────────────────────────────────────────────────────────
F += [H1("7. 本実験の限界 — 何が言えて何が言えないか")]
F += [tbl([["言えること", "根拠"],
           ["実機の 60GHz 無線がデータ経路にある", "V90 ×4 の 2 ホップ。ODU で累計 7.3GB / 9.4GB の転送を確認"],
           ["定常状態の測定は実無線上で行われた", "Tx1→Rx1 の全パケットが無線を通過"],
           ["リンク容量が実無線の実測値で決まっている", "netem ではなく iperf3 実測から CR1_BW を決定"],
           ["実無線上で SP+WRR が成立する", "AF41 が 95.7% 占有、比 66:2:1"],
           ["OSPF-SR 隣接が無線越しに成立する", "192.168.0.5 Full cr1-lere"],
           ["無線→有線の迂回効果を実測した", "0.861 → 8.055 Gbps、断 2–3 秒"]],
          [66*mm, 102*mm])]
F += [Spacer(1, 3*mm)]
F += [callout("言えないこと — 障害注入は依然としてエミュレートである",
  "障害は <font face='Courier' size='8'>docker exec LER_Ingress tc qdisc add dev leri-cr1 root netem loss 100%</font> "
  "により注入している。leri-cr1 は <b>LER_Ingress と CR1 の間の veth (有線の仮想インタフェース)</b> であり、"
  "経路上では無線の<b>手前</b>に位置する。障害中、無線リンクは完全に正常のまま動作しており、"
  "パケットが無線に到達する前に落とされているだけである。<br/><br/>"
  "したがって「無線障害からの復旧を実証した」とは言えない。"
  "あわせて、フェージング・降雨減衰・MCS 適応・ビームトラッキングといった無線特有の挙動も未評価であり、"
  "60 秒間を通じて容量は 0.861 Gbps で一定であった (時間変動する無線容量は観測していない)。")]

# ─── 8. 今後 ────────────────────────────────────────────────────────
F += [H1("8. 今後の課題")]
F += [tbl([["課題", "内容", "優先度"],
           ["アンテナの再アライメント",
            "現在の CR1_BW = 900M はアンテナをずらした状態 (実効 1.05 Gbps) の値。"
            "ずらす前は 2.36 Gbps 出ており CR1_BW = 2100M であった。子機の Tools → Aiming で "
            "Signal -38 dBm / MCS 12 を目安に合わせ直し、scripts/c2_path1_probe.sh で測り直す。", "高"],
           ["無線側での障害注入",
            "ODU は SSH サーバを持つため、frr_measure.sh の netem 挿入箇所を無線停止コマンドに"
            "差し替えれば、既存の 3 シナリオの枠組みのまま実無線の障害を注入できる。"
            "物理的な LOS 遮蔽も一度は実施する価値がある (時刻精度は落ちるが実在性は最高)。", "高"],
           ["理論値線の修正",
            "results/frr/plot_frr.py の _lab_cr_mbps() が lab_config_veth.sh を優先して読むため、"
            "グラフの理論値が有線前提の 8.00 Gbps になっている。無線経路の理論値は 0.86 Gbps。"
            "有線・無線の 2 本を描き分けるのが望ましい。", "中"],
           ["アライメント劣化条件の追加",
            "今回アンテナのずれで容量が 2.36 → 1.05 Gbps とほぼ半減した。これ自体が "
            "60GHz の脆弱性の実測データである。意図的にずらして測れば追加の比較条件になる。", "中"]],
          [40*mm, 112*mm, 16*mm])]

F += [Spacer(1, 5*mm), H2("参照")]
F += [tbl([["docs/radwin_integration_plan.md", "実測トポロジマップ・VLAN 設定計画"],
           ["scripts/radwin_verify.sh / .ps1", "無線チェーンの疎通・RTT・MTU・スループット検証"],
           ["scripts/c2_path1_probe.sh", "経路 1 の TCP / UDP スイープによる実容量測定"],
           ["scripts/c2_fabric_test.sh", "3 経路の開通試験 (経路別 MTU / レート対応済み)"],
           ["results/frr/radwin/setup/20260911_success_radwin_cr1_wireless/", "本計測データとグラフ"],
           ["results/frr/radwin/setup/20260911_fail_radwin_mtu_oversize/", "初回失敗の記録 (README.md に原因)"]],
          [70*mm, 98*mm], header=False)]

def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont(JP, 7.5)
    canvas.setFillColor(GREY)
    canvas.drawString(21*mm, 12*mm, "RADWIN TerraNet 60GHz 無線リンク導入記録 (2026-09-04 〜 09-11)")
    canvas.drawRightString(A4[0]-21*mm, 12*mm, f"- {doc.page} -")
    canvas.setStrokeColor(colors.HexColor("#BCC6D0"))
    canvas.line(21*mm, 15*mm, A4[0]-21*mm, 15*mm)
    canvas.restoreState()

out = Path(__file__).resolve().parent.parent / "docs" / "RADWIN無線導入記録_20260911.pdf"
SimpleDocTemplate(str(out), pagesize=A4,
                  leftMargin=21*mm, rightMargin=21*mm, topMargin=18*mm, bottomMargin=20*mm,
                  title="RADWIN TerraNet 60GHz 無線リンク導入記録",
                  author="frr-docker-lab-main2").build(F, onFirstPage=footer, onLaterPages=footer)
print(f"[OK] {out}")
print(f"     {out.stat().st_size:,} バイト")
