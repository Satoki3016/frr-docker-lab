#!/usr/bin/env python3
"""2026-09-12 〜 09-18 の進捗報告を PDF 化する。

前回報告 (docs/RADWIN無線導入記録_20260911.pdf) の続き。
数値はすべて results/frr/ 配下の実測値から集計したもの。
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
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

JP_FONT_PATH = "/usr/share/fonts/truetype/takao-gothic/TakaoGothic.ttf"
JP = "TakaoGothic"
pdfmetrics.registerFont(TTFont(JP, JP_FONT_PATH))

NAVY  = colors.HexColor("#183153"); BLUE  = colors.HexColor("#2878B5")
CYAN  = colors.HexColor("#DDEFF8"); GREY  = colors.HexColor("#666666")
RED   = colors.HexColor("#B03A2E"); GREEN = colors.HexColor("#1E8449")
LGREY = colors.HexColor("#F4F6F8")

ss = getSampleStyleSheet()
S = {
 "title": ParagraphStyle("t", parent=ss["Title"], fontName=JP, fontSize=19, leading=27, textColor=NAVY),
 "sub":   ParagraphStyle("s", parent=ss["Normal"], fontName=JP, fontSize=10.5, leading=16,
                         alignment=TA_CENTER, textColor=GREY),
 "h1":    ParagraphStyle("h1", parent=ss["Heading1"], fontName=JP, fontSize=14, leading=20,
                         textColor=NAVY, spaceBefore=10, spaceAfter=6),
 "h2":    ParagraphStyle("h2", parent=ss["Heading2"], fontName=JP, fontSize=11.5, leading=17,
                         textColor=BLUE, spaceBefore=8, spaceAfter=4),
 "body":  ParagraphStyle("b", parent=ss["Normal"], fontName=JP, fontSize=9.3, leading=15, spaceAfter=4),
 "cell":  ParagraphStyle("c", parent=ss["Normal"], fontName=JP, fontSize=8.3, leading=12),
 "cellb": ParagraphStyle("cb", parent=ss["Normal"], fontName=JP, fontSize=8.3, leading=12, textColor=NAVY),
 "mono":  ParagraphStyle("m", parent=ss["Normal"], fontName="Courier", fontSize=7.8, leading=11),
 "monojp":ParagraphStyle("mj", parent=ss["Normal"], fontName=JP, fontSize=7.0, leading=10.5),
 "cap":   ParagraphStyle("cp", parent=ss["Normal"], fontName=JP, fontSize=8.2, leading=12.5,
                         alignment=TA_CENTER, textColor=GREY, spaceBefore=3),
 "note":  ParagraphStyle("n", parent=ss["Normal"], fontName=JP, fontSize=8.5, leading=13, textColor=GREY),
}
def P(t, s="body"): return Paragraph(t, S[s])
def H1(t): return Paragraph(t, S["h1"])   # 孤立防止は KeepTogether 側で行う
def H2(t): return Paragraph(t, S["h2"])
W = 168*mm

def tbl(rows, widths, header=True):
    data = [[Paragraph(c, S["cellb"] if (header and r == 0) else S["cell"]) if isinstance(c, str) else c
             for c in row] for r, row in enumerate(rows)]
    st = [("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#BCC6D0")),
          ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
          ("LEFTPADDING", (0,0), (-1,-1), 4), ("RIGHTPADDING", (0,0), (-1,-1), 4),
          ("TOPPADDING", (0,0), (-1,-1), 3), ("BOTTOMPADDING", (0,0), (-1,-1), 3)]
    if header:
        st += [("BACKGROUND", (0,0), (-1,0), CYAN),
               ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, LGREY])]
    else:
        st += [("ROWBACKGROUNDS", (0,0), (-1,-1), [colors.white, LGREY])]
    t = Table(data, colWidths=widths, style=TableStyle(st), hAlign="LEFT", repeatRows=1 if header else 0)
    # 表が途中で切れると対応関係が読めなくなるため、同一ページに収める
    return KeepTogether([t])

def code(lines, style=None):
    if style is None:
        style = "monojp" if any(ord(c) > 0x7F for l in lines for c in l) else "mono"
    txt = "<br/>".join(l.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace(" ","&nbsp;")
                       for l in lines)
    return Table([[Paragraph(txt, S[style])]], colWidths=[W],
                 style=TableStyle([("BACKGROUND",(0,0),(-1,-1),LGREY),
                                   ("BOX",(0,0),(-1,-1),0.4,colors.HexColor("#BCC6D0")),
                                   ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),
                                   ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]),
                 hAlign="LEFT")

def callout(title, body, color=RED):
    bg = colors.HexColor("#FCF3F2") if color == RED else colors.HexColor("#EFF8F1")
    inner = [[Paragraph(f"<b>{title}</b>", ParagraphStyle("ct", parent=S["cell"], textColor=color))],
             [Paragraph(body, S["cell"])]]
    t = Table(inner, colWidths=[W],
              style=TableStyle([("BACKGROUND",(0,0),(-1,-1),bg), ("BOX",(0,0),(-1,-1),0.6,color),
                                ("LEFTPADDING",(0,0),(-1,-1),7),("RIGHTPADDING",(0,0),(-1,-1),7),
                                ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]),
              hAlign="LEFT")
    # 見出しと本文がページ境界で分断されると読めなくなるため、必ず同一ページに置く
    return KeepTogether([t])

def fig(path, caption, h_mm):
    return KeepTogether([Spacer(1, 2*mm), Image(path, width=W, height=h_mm*mm),
                         P(caption, "cap"), Spacer(1, 2*mm)])

ROOT = Path(__file__).resolve().parents[3]   # tools/ → frr/ → results/ → リポジトリ
F = []

# ─── 表紙 ────────────────────────────────────────────────────────────
F += [Spacer(1, 34*mm),
      P("進捗報告", "title"),
      Spacer(1, 2*mm),
      P("無線容量に追従する動的経路制御の実装と検証", "title"),
      Spacer(1, 6*mm),
      P("60GHz 無線リンクの容量変動を実時間で推定し、WCMP の重みと<br/>"
        "HTB の整形レートを自動更新する制御ループを実装・検証した。<br/>"
        "あわせて ECMP と容量比 WCMP を同一条件で比較した。", "sub"),
      Spacer(1, 10*mm),
      tbl([["対象期間", "2026-09-12 〜 2026-09-18"],
           ["前回報告", "docs/RADWIN無線導入記録_20260911.pdf (2026-09-04 〜 09-11)"],
           ["実施した計測", "10 条件 (うち有効 8 条件)"],
           ["新規スクリプト", "radwin_telemetry.py / radwin_ssh.py / radwin_wcmp_controller.py ほか"],
           ["成果物", "results/frr/radwin/dynamic/20260918_success_dynamic_control/"],
           ["訂正 (2026-09-25)", "§4.1・§4.3 の係数 0.52 の根拠を訂正 (無線の実効率は 0.568、"
                                 "2.4 Gbps は ODU の 2.5GbE ポートで頭打ちした値)"]],
          [34*mm, W-34*mm], header=False),
      Spacer(1, 8*mm),
      P("本書の数値はすべて results/frr/ 配下の計測ファイルから集計した実測値である。"
        "推定値・モデル値にはその旨を明記する。", "note"),
      PageBreak()]

# ─── 1. 到達点 ───────────────────────────────────────────────────────
F += [H1("1. 前回からの到達点"),
      P("前回報告の時点では、無線 2 ホップを CR1 経路に組み込み、単一経路で 3 シナリオを"
        "計測できた段階だった。本期間では <b>3 経路を同時に使う構成</b> に進み、"
        "さらに <b>無線容量の変動に自動追従する制御ループ</b> を実装して実測で検証した。"),
      Spacer(1, 2*mm),
      tbl([["項目", "前回 (09-11)", "今回 (09-18)"],
           ["経路の使い方", "CR1 単独 (主経路 + 障害時フォールバック)", "3 経路同時 (ECMP / 容量比 WCMP)"],
           ["フロー数", "4 本 / クラス (計 12 本)", "64 本 / クラス (計 192 本)"],
           ["無線容量の扱い", "固定値 (CR1_BW を手で設定)", "ODU テレメトリから実時間推定・自動適用"],
           ["総スループット", "0.899 Gbps (無線が律速)", "20.14 Gbps (WCMP, 無線 2.16G 時)"],
           ["障害時の AF41", "21 秒の完全断", "低下 1.6 %・断ゼロ (WCMP)"]],
          [30*mm, 62*mm, W-92*mm]),
      Spacer(1, 4*mm),
      callout("本期間で得られた主要な知見",
              "① 経路の重みが容量を反映していないと、リンクごとの優先度制御 (HTB) が成立していても "
              "<b>エンドツーエンドの優先度差が消える</b>。ECMP では AF42:AF43 = 0.98:1 となり、"
              "設計値 2:1 が失われた。<br/>"
              "② 容量比 WCMP はこれを回復し (2.00:1)、同時に <b>全リンクを 100 % 利用</b> した。<br/>"
              "③ 無線容量は静止環境でも実際に変動する。実測で 493〜2420 Mbps (4.9 倍) の幅があり、"
              "固定値による設定は原理的に追従できない。", GREEN),
      Spacer(1, 3*mm),
      P("なお本期間の作業を通じて、既存スクリプトに <b>計測データの妥当性に関わる不具合を 2 件</b> "
        "発見し修正した。詳細は第 5 章に記す。")]

# ─── 2. 実験条件の整備 ───────────────────────────────────────────────
F += [H1("2. 実験条件の整備 — 交絡要因の除去"),
      P("3 経路を同時に使う比較を行うにあたり、結果を歪める要因を順に取り除いた。"
        "いずれも「効果があるはずの機構が効いていない」または「別の要因が結果を作っていた」ものである。"),

      H2("2.1 フロー数を 64 本 / クラスに増やした"),
      P("マルチパスの分配はフロー単位のハッシュで決まるため、フロー数が少ないと分配粒度が粗くなり、"
        "重みどおりの配分にならない。従来の 4 本 / クラスでは 3 経路に分けきれないため 64 本に増やした "
        "(総送信量 24 Gbps は不変、1 本あたり 125 Mbps)。"),
      P("128 本も試したが、iperf3 の接続確立が同時に集中して一部ストリームが失敗し "
        "(AF42 が 126/128 本)、計測が欠測した。64 本を採用し、"
        "ストリーム数の自動検査と再試行を <font face='Courier'>run_all_scenarios.sh</font> に組み込んだ。", ),

      H2("2.2 入口ポリサーを外した"),
      P("LER_Ingress の入口に総容量 × 4:2:1 のポリサーが入っており、"
        "<b>経路に載せる前の段階でクラス間の差を作っていた</b>。単一経路の計測ではリンク容量の方が"
        "はるかに厳しいため表面化しなかったが、3 経路構成では総容量が増えるためポリサーが支配的になる。"),
      P("これを残したままだと「HTB による優先制御の効果」と「入口ポリサーの効果」を分離できない。"
        "<font face='Courier'>INGRESS_POLICE=auto</font> を導入し、マルチパス時は自動的に無効化するようにした。"),

      H2("2.3 経路設定が 3 箇所に分散していた"),
      P("経路の設定が <font face='Courier'>frr_dscp_te.sh</font>・<font face='Courier'>frr_measure.sh</font>・"
        "<font face='Courier'>frr_te_monitor.sh</font> の 3 箇所にあり、"
        "後から実行される frr_measure.sh がシナリオごとに CR1 単独の経路で上書きしていた。"
        "このため ROUTE_MODE を wcmp にしても計測時には単一経路に戻っていた。3 箇所すべてを "
        "ROUTE_MODE に従うよう統一した。"),

      H2("2.4 L3+L4 ハッシュの有効化"),
      P("Linux の既定 (<font face='Courier'>fib_multipath_hash_policy=0</font>) は"
        "送信元・宛先 IP のみでハッシュするため、同一クラスの 64 本はすべて同じ経路に載ってしまう。"
        "ポート番号を含む L3+L4 ハッシュ (値 1) を明示的に有効化した。"),
      callout("この設定がないとマルチパスは一切機能しない",
              "エラーは出ず、経路表には 3 本の nexthop が並んだままなので、"
              "設定ミスに気づきにくい。実際に分配されているかは "
              "<font face='Courier'>path_stats.csv</font> の経路別 TX バイト数で確認する必要がある。"),
      ]

# ─── 3. ECMP vs WCMP ─────────────────────────────────────────────────
F += [H1("3. ECMP と容量比 WCMP の比較"),
      P("3 経路の容量は CR1 (無線) だけが大きく小さい。この <b>容量の非対称性</b> に対して、"
        "等分配 (ECMP) と容量比分配 (WCMP) がそれぞれどう振る舞うかを同一条件で比較した。"
        "無線容量が 0.9 Gbps の条件と 2.16 Gbps の条件の 2 水準で実施している "
        "(前者はアンテナ調整前、後者は調整後の実測値)。"),
      Spacer(1, 1*mm),
      tbl([["条件", "CR1 (無線)", "CR2 / CR3 (有線)", "重み CR1:CR2:CR3"],
           ["ECMP", "0.9 または 2.16 Gbps", "各 9 Gbps", "1 : 1 : 1"],
           ["WCMP", "同上", "各 9 Gbps", "容量比 (例 6:25:25)"]],
          [24*mm, 40*mm, 38*mm, W-102*mm]),
      Spacer(1, 2*mm),
      P("送信は AF41 / AF42 / AF43 の 3 クラス × 64 フロー、各クラス 8 Gbps、"
        "合計 24 Gbps でリンク容量を意図的に超過させている (輻輳は本実験の前提条件)。"),
      fig(str(ROOT/"results/frr/radwin/dynamic/20260918_success_dynamic_control/ecmp_vs_wcmp.png"),
          "図 1  ECMP と容量比 WCMP の比較 (normal シナリオ、t = 5〜55 s の平均)。"
          "(a) クラス別スループット。(b) 各経路の容量利用率。", 72),

      H2("3.1 ECMP は優先度制御を壊す"),
      P("最も重要な結果は AF42 と AF43 の比である。HTB の quantum は 2:1 に設定してあり、"
        "輻輳時には AF42 が AF43 の 2 倍のスループットを得るのが設計値である。"),
      Spacer(1, 1*mm),
      tbl([["条件", "AF41", "AF42", "AF43", "AF42 : AF43", "合計"],
           ["ECMP (無線 0.9G)", "6.268", "5.181", "5.294", "<b>0.98 : 1</b>", "16.744"],
           ["WCMP (無線 0.9G)", "8.048", "7.228", "3.614", "<b>2.00 : 1</b>", "18.890"],
           ["ECMP (無線 2.16G)", "7.845", "5.846", "4.876", "1.20 : 1", "18.567"],
           ["WCMP (無線 2.16G)", "8.045", "6.875", "5.223", "1.32 : 1", "20.143"]],
          [40*mm, 20*mm, 20*mm, 20*mm, 26*mm, W-126*mm]),
      P("単位はすべて Gbps。", "note"),
      Spacer(1, 2*mm),
      P("ECMP (無線 0.9G) では AF42 : AF43 が <b>0.98 : 1</b> となり、優先度の差が完全に消えている。"
        "各リンク上では HTB が正しく 2:1 で分配しているにもかかわらず、である。"),
      P("原因は、ECMP が容量を見ずに 1/3 ずつ送るため、<b>0.9 Gbps の無線経路に 1/3 のトラフィックが"
        "押し込まれて大量に廃棄される</b>ことにある。この廃棄はクラスに関係なく起きるため、"
        "リンク単位で作った優先度差が経路選択の段階で打ち消される。"),
      callout("経路選択が先、スケジューリングが後",
              "各リンクの HTB がどれだけ正しく動いていても、そこへ到達するトラフィックの割り当てが"
              "容量を無視していれば、エンドツーエンドの優先度は保証されない。"
              "<b>優先度制御は経路選択と独立には設計できない。</b>"),
      Spacer(1, 2*mm),
      P("なお無線容量が 2.16 Gbps の条件では ECMP でも 1.20:1 まで回復している。"
        "経路間の容量格差が 10 倍から 4.2 倍に縮まったためで、"
        "<b>容量を見ない分配の害は経路間の容量格差に比例して大きくなる</b>ことを示している。"),

      H2("3.2 容量利用率"),
      P("図 1(b) のとおり、WCMP は 2 条件とも <b>3 経路すべてを 100 % 利用</b> した。"
        "一方 ECMP は無線経路を 100 % 使い切る一方で有線側が余っており "
        "(無線 0.9G 条件で CR2 = 82 %、無線 2.16G 条件で CR3 = 82 %)、"
        "総スループットで 12.8 % / 8.5 % の差になった。"),
      P("ECMP で有線が余るのは、無線に割り当てられて廃棄されたトラフィックが"
        "他経路へ回されないためである。等分配は「公平」に見えて、"
        "容量が非対称な場合には全体の利用効率も下げる。"),

      H2("3.3 障害時の耐性"),
      P("t = 20 s に CR1 (無線) へ 100 % 損失を注入し、t = 40 s に解除する。"
        "下表は障害中 (t = 22〜39 s) の AF41 スループットを障害前 (t = 5〜19 s) と比較したものである。"),
      Spacer(1, 1*mm),
      tbl([["構成", "障害前", "障害中", "変化", "AF41 の断"],
           ["単一経路 (CR1 のみ)", "0.861", "0.000", "<b>−100 %</b>", "<b>21 秒</b>"],
           ["ECMP (無線 0.9G)", "5.011", "4.148", "−17.2 %", "0 秒"],
           ["WCMP (無線 0.9G)", "8.048", "7.918", "<b>−1.6 %</b>", "0 秒"],
           ["ECMP (無線 2.16G)", "8.037", "6.158", "−23.4 %", "0 秒"],
           ["WCMP (無線 2.16G)", "8.045", "6.786", "−15.6 %", "0 秒"]],
          [46*mm, 20*mm, 20*mm, 22*mm, W-108*mm]),
      P("単位 Gbps。迂回なし (failure シナリオ) の値。OSPF-SR による迂回を有効にした "
        "failure_reroute では、WCMP・ECMP とも AF41 の低下は 1 % 未満に収まる。", "note"),
      Spacer(1, 2*mm),
      P("単一経路では 21 秒間の完全断が生じるのに対し、3 経路構成ではいずれも断がない。"
        "無線容量が 0.9 Gbps の条件で WCMP の低下が 1.6 % にとどまるのは、"
        "WCMP がもともと無線経路に全体の 4.8 % しか載せていないためである。"
        "無線容量が 2.16 Gbps では無線の担当分が 10.7 % に増えるため、失う量も増えて −15.6 % となる。"),
      callout("重み付けは障害耐性も同時に与える",
              "容量比 WCMP は、脆弱なリンクに対して自動的に「そのリンクが落ちても影響が小さい」"
              "配分を与える。冗長化のための追加機構ではなく、"
              "容量に応じた配分という一つの原理から帯域効率と障害耐性の両方が得られる。", GREEN),

      H2("3.4 再現性"),
      P("同一条件を 3 回 (normal / failure / failure_reroute の障害前区間) 計測したときの "
        "AF41 のばらつきを比較すると、両者の差は大きい。"),
      Spacer(1, 1*mm),
      tbl([["条件", "3 回の AF41", "幅"],
           ["ECMP (無線 0.9G)", "6.268 / 5.011 / 6.645 Gbps", "<b>± 14 %</b>"],
           ["WCMP (無線 0.9G)", "8.048 / 8.048 / 8.048 Gbps", "<b>± 0.02 % 未満</b>"]],
          [40*mm, 70*mm, W-110*mm]),
      Spacer(1, 2*mm),
      P("ECMP のばらつきは、どのフローがハッシュで無線経路に落ちるかが試行ごとに変わるためである。"
        "容量の小さい経路に載ったフローは大量に廃棄されるので、"
        "<b>どのクラスのフローが何本そこに当たったかが結果を左右する</b>。"
        "WCMP では無線経路の担当分が容量に見合っているため、この感度が消える。"),
      P("実験の再現性という観点からも、容量を反映した重み付けは必要である。"),
      ]

# ─── 4. 動的制御 ─────────────────────────────────────────────────────
F += [H1("4. 無線容量に追従する動的制御"),
      P("第 3 章の WCMP は重みを手で与えている。しかし無線容量は固定ではない。"
        "重みと HTB の整形レートを <b>実際の無線容量から自動生成する</b> 制御ループを実装した。"),

      H2("4.1 ODU テレメトリの取得"),
      P("V90 の各 ODU から <font face='Courier'>iw dev wlan0 station dump</font> を実行し、"
        "PHY レート・MCS・受信電力を読む。ODU の SSH は dropbear v2019.78 で、"
        "公開鍵認証が (正しく配置しても) 拒否されたため、"
        "Python の <font face='Courier'>pty.fork()</font> によるパスワード自動応答で接続している。"
        "パスワードは <font face='Courier'>~/.radwin_pass</font> (600) に置き、スクリプトには埋め込まない。"),
      P("チェーン全体の実効容量は次式で推定する。2 ホップは直列なので小さい方が律速し、"
        "TDD 半二重などのため実効値は PHY レートより大きく下がる。"),
      P("<b>[2026-09-25 訂正]</b> 当初は係数 0.52 を「PHY の約 52 % が実効値」と説明したが、"
        "これは無線の効率ではない。無線そのものの効率は、MCS 12 (PHY 4620 Mbps) で "
        "ODU 内蔵 SpeedTest 2624 Mbps、prs-link-estimator の currentThroughput 12 回平均 2623 Mbps から "
        "<b>0.568</b> と実測した。0.52 は、低い MCS での効率を測っていないため、0.568 より保守側の値として残している。"),
      code(["C_chain = min(PHY_hop1, PHY_hop2) × 0.52",
            "CR1_BW  = C_chain × 0.9              (安全率)",
            "w1      = round(CR1_BW / 9000 × 100)  (w2 = w3 = 100 に固定)"]),

      H2("4.2 制御則 — 非対称なヒステリシス"),
      P("容量の推定値が現在値から ±10 % 以上変化したときに更新する。ただし <b>下げと上げで扱いを変える</b>。"),
      Spacer(1, 1*mm),
      tbl([["方向", "条件", "理由"],
           ["下げ", "1 回の観測で即座に適用", "容量を過大評価したままだと無線が溢れて損失が出る。安全側に倒す"],
           ["上げ", "3 回連続で確認してから適用", "一時的な改善で上げると、直後に戻ったとき過大評価になる"]],
          [18*mm, 44*mm, W-62*mm]),
      Spacer(1, 2*mm),
      P("リンクが完全に切れた場合は制御ループでは経路を触らない。"
        "OSPF と <font face='Courier'>frr_te_monitor.sh</font> が担当しており、二重に操作すると競合するためである。"),
      P("また、前提条件 (HTB qdisc の存在・経路が 3 本 nexthop であること・"
        "L3+L4 ハッシュが有効であること) を起動時に検査し、"
        "未達なら <b>適用せず中止する</b>。適用が失敗した場合も内部状態を進めず、"
        "ログに <font face='Courier'>_FAIL</font> を残して次回再試行する。"),
      callout("「制御したつもり」を残さない",
              "tc や ip route は対象が無くても静かに失敗することがある。"
              "検査と失敗記録がないと、何も適用されないまま正常なログだけが残り、"
              "後から見て区別がつかない。実際にこの検査が、"
              "前回計測の残骸で HTB が消えていた状態を検出した (5.1 節)。"),

      H2("4.3 実測による検証"),
      P("トラフィックを流した状態で制御ループを動作させ、途中で手動でアンテナの向きを変えて"
        "容量を変動させた。網掛けが手動操作を行った区間である。"),
      fig(str(ROOT/"results/frr/radwin/dynamic/20260918_success_dynamic_control/dynamic_control.png"),
          "図 2  無線容量の変動に対する制御の追従。(a) 実測スループット・推定容量・適用した整形レート。"
          "(b) 各ホップの MCS と受信電力。網掛けは手動でアンテナを操作した区間。", 122),
      Spacer(1, 1*mm),
      tbl([["項目", "結果"],
           ["観測時間 / サンプル数", "122 秒 / 62 サンプル (2 秒間隔)"],
           ["実測スループットの変動", "493 〜 2420 Mbps (<b>4.9 倍</b>)"],
           ["制御動作", "down 5 回 / up 5 回 / keep 37 回"],
           ["適用失敗", "<b>0 回</b>"],
           ["低下の検知遅れ", "1 ポーリング以内 (≤ 2 秒)"],
           ["上昇の反映遅れ", "3 ポーリング (5.7 秒) — 設計どおり"],
           ["却下された上昇", "<b>7 回中 2 回</b> (確認中に容量が戻らず、正しく見送り)"]],
          [48*mm, W-48*mm]),
      Spacer(1, 2*mm),
      P("特筆すべきは <b>7 回の上昇候補のうち 2 回が却下された</b>ことである。"
        "いずれも 2 回目の確認までは条件を満たしたが、3 回目までに容量が戻らなかった。"
        "即座に上げていれば過大評価となっていたケースであり、非対称ヒステリシスが"
        "実データで機能することを示している。フラッピングは一度も発生していない。"),
      P("また、容量を最大値 (2162M) まで上げた状態が最も安定していた (MCS 12/12 を 20 秒維持)。"
        "「容量を上げる → トラフィック増 → 干渉 → 容量低下」という正のフィードバックは観測されなかった。"),

      H2("4.4 推定式の精度と限界"),
      P("推定容量と実測スループットの相関係数は <b>r = 0.891</b> であった。"
        "ただし精度は状況によって大きく異なる。"),
      Spacer(1, 1*mm),
      tbl([["区間", "推定", "実測", "誤差"],
           ["安定時 (MCS 12/12、24 サンプル)", "2402 Mbps", "2360 Mbps", "<b>−1.7 %</b>"],
           ["回復直後 (t = 84〜100 s)", "1301 Mbps", "2130 Mbps", "<b>−39 %</b> (過小評価)"]],
          [58*mm, 26*mm, 26*mm, W-110*mm]),
      Spacer(1, 2*mm),
      P("安定時は推定と実測の差が 1.7 % であった。"
        "<b>[2026-09-25 訂正]</b> 当初はこれをモデルの独立した裏付けとしたが、誤りである。"
        "実測 2360 Mbps は ODU の 2.5GbE ポート (実効約 2475 Mbps) で頭打ちした値で、"
        "無線はそれより多く運べる (上記の 2624 Mbps)。一致は偶然であり、"
        "安定時の推定 (2402 Mbps) は無線の実容量に対し約 8 % 保守側である。"),
      P("一方、<b>回復の過渡状態では大きく過小評価する</b>。図 2(a) で実測 (黒線) は t ≈ 79 s に"
        "2100 Mbps へ跳ね上がっているが、適用値 (青破線) が追いつくのは t = 106 s で、"
        "<b>27 秒の遅れ</b>がある。この間、無線は平均 2170 Mbps 出せたのに制御は 1171M しか許可していない。"),
      P("原因は図 2(b) に現れている。<font face='Courier'>iw</font> が返す tx bitrate は"
        "<b>直前に送信したフレームのレート</b>であり、レート適応が段階的に MCS を上げていく過程を"
        "そのまま反映する。実際に出せるスループットより低い値が続くため、推定が遅れる。"),
      callout("安全側の誤りだが、無線容量を捨てている",
              "過小評価なので通信が途切れることはない (余剰は有線経路が吸収する)。"
              "しかし 27 秒間にわたり無線容量の約半分を使わずにいた。"
              "改善案は、<b>下げは MCS 基準のまま (速く安全側)、"
              "上げは実測スループット基準に変える</b>こと。"
              "経路別の送信バイト数は既に path_stats.csv で取得しているため、同じ手段で実装できる。"),
      ]

# ─── 5. 発見した不具合 ───────────────────────────────────────────────
F += [H1("5. 発見した不具合と修正"),
      P("本期間の作業を通じて、既存スクリプトに計測データの妥当性に関わる不具合を発見した。"
        "いずれもエラーを出さずに進行するため、結果を見ただけでは気づけない種類のものである。"),

      H2("5.1 障害注入が HTB を破壊していた (データ妥当性に影響)"),
      P("<font face='Courier'>frr_measure.sh</font> の障害注入は "
        "<font face='Courier'>tc qdisc add dev leri-cr1 root netem loss 100%</font> で行っており、"
        "これが <b>HTB の root qdisc を置き換えていた</b>。"
        "さらに t = 40 s の解除処理が <font face='Courier'>tc qdisc del ... root</font> を"
        "無条件に実行するため、<b>netem もろとも HTB が消え、再設定されないまま計測が続いていた</b>。"),
      P("検出は経路別送信レートの比較による。障害前は CR1 が設定値ちょうどに張り付くのに対し、"
        "復旧後は必ず設定値を超えていた。"),
      Spacer(1, 1*mm),
      tbl([["計測", "CR1_BW 設定", "障害前 (t = 15〜19 s)", "復旧後 (t = 45〜55 s)"],
           ["20260918_wcmp / failure_reroute", "0.900 G", "0.900 Gbps", "<b>2.013 Gbps</b>"],
           ["20260918_wcmp / failure", "0.900 G", "0.900 Gbps", "<b>1.132 Gbps</b>"],
           ["20260918_wcmp_ref / failure_reroute", "2.160 G", "2.160 Gbps", "<b>2.444 Gbps</b>"],
           ["20260918_wcmp_ref / failure", "2.160 G", "2.160 Gbps", "<b>3.272 Gbps</b>"]],
          [58*mm, 24*mm, 38*mm, W-120*mm]),
      Spacer(1, 2*mm),
      P("障害前が小数第 3 位まで設定値と一致し、復旧後だけが超過している。整形が失われた証拠である。"),
      P("<b>修正:</b> netem を HTB の root ではなく <b>葉クラス (1:1 / 1:2 / 1:3) に付ける</b>方式へ変更した。"
        "解除しても HTB が残る。1:3 は HTB の default クラスでもあるため、"
        "fwmark の付かない OSPF hello もここに落ち、隣接断の再現性は保たれる。"),
      callout("過去データへの影響範囲",
              "<b>影響なし:</b> normal シナリオ全体 (netem を使わない)。"
              "failure 系の t = 0〜40 s (障害検知・迂回の評価は有効)。<br/>"
              "<b>無効:</b> failure 系の t ≧ 43 s (復旧後)。無線経路が無整形になり CR1 が設定容量を超える。"
              "本報告の第 3.3 節は t = 0〜40 s のみを集計している。"
              "復旧後の数値を用いる場合は再計測が必要である。"),

      H2("5.2 HTB の default クラスが存在しない"),
      P("<font face='Courier'>frr_dscp_te.sh</font> は "
        "<font face='Courier'>htb default 13</font> を指定しているが、"
        "実在するクラスは 1:0 / 1:1 / 1:2 / 1:3 のみで <b>1:13 は存在しない</b>。"
        "HTB は default が存在しないクラスを指すと未分類パケットを direct queue へ流すため、"
        "<b>整形を一切受けない</b>。"),
      P("本番計測では全トラフィックが fwmark または MPLS (0x8847) のフィルタにマッチするため実害はない。"
        "ただし <b>アドホックな帯域プローブは素通りする</b>。"
        "実際、CR1_BW を 360〜540M に設定していた約 42 秒間も、"
        "fwmark のない TCP は一度も 0.6 Gbps を下回らず、最大 2.420 Gbps まで出た。"),
      P("HTB の効きを検証する際は必ず fwmark 付きのトラフィック、"
        "または MPLS 経由の本番パスを使うこと。", "note"),

      H2("5.3 無線の MCS はトラフィックがないと上がらない"),
      P("不具合ではないが、計測手順に影響する重要な性質である。"
        "802.11ad のレート適応は実データの成功率を観測して MCS を決めるため、"
        "<b>通信がないと低い MCS に留まったまま動かない</b>。"),
      P("実測では、無通信の状態で 72 秒間 MCS 9 のまま変化しなかったものが、"
        "iperf3 を流した 12 秒後には MCS 12 に達した。"),
      callout("切り分けは受信電力と MCS の不一致で行う",
              "この現象は「アンテナを元に戻したのにスループットが戻らない」という形で現れ、"
              "アライメント不良と誤診しやすい。決め手は受信電力である。<br/>"
              "実測例: 無線 1 = MCS 12 / −30 dBm、無線 2 = MCS 9 / −28 dBm。"
              "<b>信号が良い方の MCS が低い</b>ため伝搬の問題ではないと確定できた。"
              "この判断のため、制御ループの記録項目に受信電力を追加した。", GREEN),
      ]

# ─── 6. 残課題 ───────────────────────────────────────────────────────
F += [H1("6. 現時点の到達点と残課題"),
      P("最終目標は「障害や輻輳が発生しても、自動で検知してリルーティングと輻輳制御を行い、"
        "途切れない通信を実現する」ことである。現時点の達成状況は次のとおり。"),
      Spacer(1, 1*mm),
      tbl([["要素", "状況", "根拠"],
           ["輻輳下の優先度制御", "達成", "WCMP で AF42:AF43 = 2.00:1 (設計値どおり)"],
           ["リンク障害の自動迂回", "達成", "failure_reroute で AF41 低下 1 % 未満・断ゼロ"],
           ["容量低下の自動検知", "達成", "MCS 変化を 2 秒以内に検知、誤検知ゼロ"],
           ["容量に応じた自動再配分", "達成", "重みと HTB を自動更新、適用失敗ゼロ"],
           ["本番トラフィックでの統合検証", "<b>未実施</b>", "制御ループと 3 クラス計測は未だ別々に実行"],
           ["回復時の追従速度", "<b>要改善</b>", "27 秒の遅れ (4.4 節)"]],
          [42*mm, 20*mm, W-62*mm]),
      Spacer(1, 3*mm),

      H2("6.1 次に行うべきこと"),
      P("<b>(1) 本番トラフィックを流した状態での統合検証。</b> "
        "現時点では制御ループの検証 (単一フローのプローブ) と 3 クラス計測が別々に行われている。"
        "AF41 / AF42 / AF43 を流しながら無線容量を変動させ、"
        "<b>容量が変わっても優先度制御が維持され、AF41 が途切れないこと</b>を示す必要がある。"
        "これが最終目標の直接的な証拠になる。"),
      P("<b>(2) 回復時の追従改善。</b> 上げ方向の判断を実測スループット基準に変更する (4.4 節)。"
        "ただし (1) を先に行えば、現在の 27 秒の遅れが優先度制御に"
        "どの程度影響するかを実測できる。改善後との比較対象になるため、"
        "<b>(1) を先に実施することを推奨する</b>。"),
      P("<b>(3) failure 系シナリオの再計測。</b> 5.1 節の修正後、"
        "復旧後区間を含む完全なデータを取り直す。"),
      P("<b>(4) 20260918_ecmp_ref の再計測。</b> "
        "AF43 が 62/64 本しか接続できず欠測している (normal シナリオが無効)。"),
      Spacer(1, 4*mm),

      H2("6.2 成果物の所在"),
      tbl([["results/frr/radwin/dynamic/20260918_success_dynamic_control/", "本報告の図 1・図 2 と生成スクリプト"],
           ["results/frr/radwin/comparison/20260918_wcmp/, _wcmp_ref/", "WCMP 計測 (無線 0.9G / 2.16G)"],
           ["results/frr/radwin/comparison/20260918_ecmp_nopolice/, _ecmp_ref2/", "ECMP 計測 (同上)"],
           ["scripts/radwin_telemetry.py", "ODU テレメトリ取得と容量推定"],
           ["scripts/radwin_wcmp_controller.py", "制御ループ本体"],
           ["scripts/radwin_ssh.py", "dropbear 向け pty パスワード SSH"],
           ["results/frr/tools/plot_dynamic_control.py, plot_ecmp_wcmp.py", "図の生成"],
           ["/tmp/radwin_controller.csv", "制御ループのログ (図 2 の元データ)"]],
          [68*mm, W-68*mm], header=False),
      Spacer(1, 4*mm),
      P("本報告の数値はすべて上記ディレクトリの計測ファイルから集計した。"
        "集計に用いた区間・条件は各節に明記している。", "note")]

def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont(JP, 7.5); canvas.setFillColor(GREY)
    canvas.drawString(21*mm, 12*mm, "進捗報告 — 無線容量に追従する動的経路制御 (2026-09-12 〜 09-18)")
    canvas.drawRightString(A4[0]-21*mm, 12*mm, f"- {doc.page} -")
    canvas.setStrokeColor(colors.HexColor("#BCC6D0"))
    canvas.line(21*mm, 15*mm, A4[0]-21*mm, 15*mm)
    canvas.restoreState()

# 初版 (docs/進捗報告_動的制御_20260918.pdf) は残し、訂正版を別名で出力する
out = ROOT / "docs" / "進捗報告_動的制御_20260918_訂正版.pdf"
SimpleDocTemplate(str(out), pagesize=A4,
                  leftMargin=21*mm, rightMargin=21*mm, topMargin=18*mm, bottomMargin=20*mm,
                  title="進捗報告 — 無線容量に追従する動的経路制御",
                  author="frr-docker-lab-main2").build(F, onFirstPage=footer, onLaterPages=footer)
print(f"[OK] {out}")
print(f"     {out.stat().st_size:,} バイト")
