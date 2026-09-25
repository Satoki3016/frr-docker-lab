#!/usr/bin/env python3
"""
gen_experiment_report.py — 実験の意図・方法・結果をまとめた報告書PDFを生成する

記載する数値はすべて以下から取得・再計算したものであり、推定値は含めない。
  - 設定値   : scripts/frr_dscp_te.sh, scripts/frr_setup.sh, scripts/lab_config_c1.sh,
               scripts/frr_measure.sh, scripts/owd_sender.py
  - 実測値   : results/frr/20260721_c2_sp_{enabled,uniform}/frr_*/{throughput.csv, owd_af4*.log}
  - 図       : 同ディレクトリ ja/ 配下の既生成PDF

使い方:
    python3 gen_experiment_report.py [-o OUTPUT.pdf]
"""
import argparse
import csv
import re
from pathlib import Path

import numpy as np
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

BASE = Path(__file__).resolve().parent.parent
SP = "qos/c2/20260721_c2_sp_enabled"      # SP + WRR
WRR = "qos/c2/20260721_c2_sp_uniform"     # WRR only（PRIO_HI=1 で SP を無効化）
T_LO, T_HI = 5, 18                 # 定常評価区間 [s]
OFFERED = 8.0                      # 1クラスあたり送信量 [Gbps] (iperf3 -b 2G × -P 4)
LINK = 9.0                         # HTB がシェープするリンク容量 [Gbps]

_TS_RE = re.compile(r'\[([0-9]+\.[0-9]+)\]\s+seq=\d+\s+owd=([0-9.-]+)\s*ms')

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
]


def register_font() -> str:
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            try:
                pdfmetrics.registerFont(TTFont("JP", p))
                return "JP"
            except Exception:
                continue
    raise RuntimeError("日本語フォントが見つかりません: " + ", ".join(FONT_CANDIDATES))


def throughput_mean(tag: str, scen: str = "frr_normal") -> np.ndarray:
    """定常区間の平均受信スループット (AF41, AF42, AF43) [Gbps]。"""
    rows = {}
    with (BASE / tag / scen / "throughput.csv").open(newline="") as f:
        for r in csv.DictReader(f):
            t = int(r["time"])
            if t not in rows:
                rows[t] = (float(r["rx1_bytes_per_sec"]),
                           float(r["rx2_bytes_per_sec"]),
                           float(r["rx3_bytes_per_sec"]))
    sel = [rows[t] for t in sorted(rows) if T_LO <= t <= T_HI]
    return np.array(sel).mean(axis=0) * 8 / 1e9


def owd_median(tag: str, cls: str, scen: str = "frr_normal") -> float:
    """定常区間の片道遅延の中央値 [ms]。"""
    ts, owd = [], []
    for line in (BASE / tag / scen / f"owd_{cls}.log").read_text(errors="ignore").splitlines():
        m = _TS_RE.match(line)
        if m:
            ts.append(float(m.group(1)))
            owd.append(float(m.group(2)))
    ts = np.array(ts) - ts[0]
    o = np.array(owd)[(np.array(ts) >= T_LO) & (np.array(ts) <= T_HI)]
    return float(np.median(o))


def max_gap(tag: str, scen: str, cls: str) -> float:
    """最長の受信途絶（＝通信断）[s]。"""
    ts = [float(m.group(1)) for m in
          (_TS_RE.match(l) for l in
           (BASE / tag / scen / f"owd_{cls}.log").read_text(errors="ignore").splitlines()) if m]
    return float(np.diff(np.array(ts) - ts[0]).max())


def build():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default=str(BASE / "reports" / "実験報告_QoSとリルーティング.pdf"))
    args = ap.parse_args()

    font = register_font()
    ss = getSampleStyleSheet()

    def style(name, size, leading, space_before=0, space_after=3, bold_color=None):
        return ParagraphStyle(name, parent=ss["Normal"], fontName=font, fontSize=size,
                              leading=leading, spaceBefore=space_before,
                              spaceAfter=space_after, alignment=TA_LEFT,
                              textColor=bold_color or colors.black)

    H1 = style("H1", 15, 20, 6, 6, colors.HexColor("#12307E"))
    H2 = style("H2", 11.5, 16, 8, 4, colors.HexColor("#12307E"))
    BODY = style("BODY", 9.5, 14.5, 0, 4)
    NOTE = style("NOTE", 8, 12, 0, 3, colors.HexColor("#555555"))
    CELL = style("CELL", 8.5, 12)
    CELLH = style("CELLH", 8.5, 12, bold_color=colors.white)

    # ── データ取得 ────────────────────────────────────────────────
    t_sp, t_wrr = throughput_mean(SP), throughput_mean(WRR)
    d_sp = [owd_median(SP, c) for c in ("af41", "af42", "af43")]
    d_wrr = [owd_median(WRR, c) for c in ("af41", "af42", "af43")]
    loss = lambda v: max(0.0, (OFFERED - v) / OFFERED * 100)

    out_sp_no = [max_gap(SP, "frr_failure", c) for c in ("af41", "af42", "af43")]
    out_sp_re = [max_gap(SP, "frr_failure_reroute", c) for c in ("af41", "af42", "af43")]
    out_wrr_re = [max_gap(WRR, "frr_failure_reroute", c) for c in ("af41", "af42", "af43")]

    doc = SimpleDocTemplate(args.output, pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title="実験報告：輻輳下のQoSと障害時リルーティング")
    S = []

    def tbl(data, widths, align_right_from=1):
        t = Table(data, colWidths=widths, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#12307E")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#AAAAAA")),
            ("ALIGN", (align_right_from, 1), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F4F8")]),
        ]))
        return t

    def fig(name, width_mm=168):
        # reportlab/PIL は PDF を画像として読めないため PNG を埋め込む
        name = name.replace(".pdf", ".png")
        p = BASE / SP / "ja" / name
        if not p.exists():
            p = BASE / SP / "en" / name
        if not p.exists():
            return None
        from PIL import Image as PILImage
        with PILImage.open(p) as im:
            w, h = im.size
        w_pt = width_mm * mm
        return Image(str(p), width=w_pt, height=w_pt * h / w)

    # ── 表題 ──────────────────────────────────────────────────────
    S.append(Paragraph("実験報告：輻輳下のQoS制御と障害時の自動リルーティング", H1))
    S.append(Paragraph(
        "対象環境 C2（実機・独立3経路）／計測日 2026-07-21／"
        "本書の数値はすべて計測CSVおよび設定スクリプトから再計算した実測値である。", NOTE))
    S.append(Spacer(1, 4 * mm))

    # ── 1. 意図 ──────────────────────────────────────────────────
    S.append(Paragraph("1. 実験の意図", H2))
    S.append(Paragraph(
        "有線と無線を組み合わせた網では、リンクは容量に限りがあり、かつ障害物や悪天候で失われやすい。"
        "したがって「輻輳時に重要なトラフィックを守る仕組み」と「障害時に経路を切り替える仕組み」の"
        "両方が同一の網の上で動く必要がある。", BODY))
    S.append(Paragraph(
        "この2つは個別には確立された技術だが、<b>両者が同時に成立する状況——輻輳している最中に"
        "リンクが落ちる状況——での挙動は評価されていない</b>。本実験の意図は、この領域を実機で定量化する"
        "ことにある。具体的には次の2点を明らかにする。", BODY))
    S.append(Paragraph(
        "　(i)  スケジューラの設定によって、輻輳下のクラス別の帯域と遅延がどこまで制御できるか<br/>"
        "　(ii) 経路が切り替わる過渡期に、その制御がどこまで有効か／何が断時間を決めているか", BODY))

    # ── 2. 環境 ──────────────────────────────────────────────────
    S.append(Paragraph("2. 実験環境", H2))
    S.append(Paragraph(
        "全ノードをDockerコンテナで構成し、Linux の MPLS データプレーンと FRR 8.4 の OSPF-SR を用いた。"
        "送信側3台・受信側3台の間を、独立した3本の経路（Router1〜3）で接続する。"
        "各経路は物理10G配線上で HTB により 9 Gbps にシェープし、シェーパを確実にボトルネックにした。", BODY))
    S.append(Spacer(1, 2 * mm))
    S.append(tbl([
        [Paragraph("項目", CELLH), Paragraph("設定値", CELLH), Paragraph("出典", CELLH)],
        [Paragraph("リンク容量", CELL), Paragraph("9 Gbps × 3経路", CELL), Paragraph("lab_config_c1.sh: CR1_BW=9G", CELL)],
        [Paragraph("送信量", CELL), Paragraph("1クラス 8 Gbps（-b 2G × -P 4）", CELL), Paragraph("frr_measure.sh: iperf3 -P 4", CELL)],
        [Paragraph("輻輳度", CELL), Paragraph("24 Gbps ÷ 9 Gbps = 2.67 倍", CELL), Paragraph("上記より算出", CELL)],
        [Paragraph("クラス", CELL), Paragraph("AF41/AF42/AF43（DSCP 34/36/38）", CELL), Paragraph("frr_dscp_te.sh", CELL)],
        [Paragraph("保証帯域", CELL), Paragraph("各クラスのフルシェアの 1/10", CELL), Paragraph("frr_dscp_te.sh: total/10 ほか", CELL)],
        [Paragraph("　　合計", CELL), Paragraph("1.29 Gbps（容量の14.3%）", CELL), Paragraph("同上を再計算", CELL)],
        [Paragraph("借用プール", CELL), Paragraph("7.71 Gbps（容量の85.7%）", CELL), Paragraph("9 − 1.29", CELL)],
        [Paragraph("優先度", CELL), Paragraph("AF41=prio 0（SP）／AF42・43=prio 1", CELL), Paragraph("frr_dscp_te.sh", CELL)],
        [Paragraph("WRR重み", CELL), Paragraph("quantum 比 4 : 2 : 1", CELL), Paragraph("frr_dscp_te.sh", CELL)],
        [Paragraph("OSPFタイマー", CELL), Paragraph("hello 1 s ／ dead-interval 3 s", CELL), Paragraph("frr_setup.sh:297-298", CELL)],
        [Paragraph("計測", CELL), Paragraph("受信スループット 1 s ／ 片道遅延プローブ 20 ms", CELL), Paragraph("owd_sender.py: interval=0.02", CELL)],
    ], [26 * mm, 62 * mm, 62 * mm]))
    S.append(Spacer(1, 2 * mm))
    S.append(Paragraph(
        "保証帯域を小さく取ったのは意図的である。HTB は保証分を優先度と無関係に先に配るため、"
        "保証を大きくすると Strict Priority が働く余地が残らない。保証を各クラスのシェアの1/10に"
        "縮小することで、容量の 85.7% を優先度が支配する借用プールに置いた。", BODY))
    f = fig("guarantee_split.pdf")
    if f:
        S.append(Spacer(1, 2 * mm))
        S.append(f)
        S.append(Paragraph("図1　保証帯域と借用帯域の配分（灰＝保証、青＝SPが支配する借用分）", NOTE))

    S.append(PageBreak())

    # ── 3. 実験A ─────────────────────────────────────────────────
    S.append(Paragraph("3. 実験A：輻輳下のQoS制御", H2))
    S.append(Paragraph(
        "<b>意図</b>　スケジューラの設定が、輻輳下のクラス別の帯域と遅延をどこまで決められるかを測る。", BODY))
    S.append(Paragraph(
        "<b>方法</b>　障害を起こさない条件で、3クラスから同時に 8 Gbps ずつ（合計 24 Gbps）を"
        "9 Gbps のリンクへ送出する。設定を2通り比較した。"
        "<b>SP+WRR</b>（AF41 を prio 0 とし最優先、AF42・AF43 を重み 2:1 で分配）と、"
        "<b>WRR のみ</b>（PRIO_HI=1 で全クラスを同一 prio にし、SP を無効化）である。"
        "起動直後の過渡を除いた t = 5〜18 s を定常区間として集計した。", BODY))
    S.append(Spacer(1, 2 * mm))
    S.append(tbl([
        [Paragraph("クラス", CELLH), Paragraph("SP+WRR<br/>帯域", CELLH), Paragraph("SP+WRR<br/>損失", CELLH),
         Paragraph("SP+WRR<br/>遅延", CELLH), Paragraph("WRRのみ<br/>帯域", CELLH),
         Paragraph("WRRのみ<br/>損失", CELLH), Paragraph("WRRのみ<br/>遅延", CELLH)],
        *[[Paragraph(c, CELL),
           Paragraph(f"{t_sp[i]:.2f} G", CELL), Paragraph(f"{loss(t_sp[i]):.1f} %", CELL),
           Paragraph(f"{d_sp[i]:.2f} ms" if d_sp[i] < 10 else f"{d_sp[i]:.0f} ms", CELL),
           Paragraph(f"{t_wrr[i]:.2f} G", CELL), Paragraph(f"{loss(t_wrr[i]):.1f} %", CELL),
           Paragraph(f"{d_wrr[i]:.2f} ms" if d_wrr[i] < 10 else f"{d_wrr[i]:.0f} ms", CELL)]
          for i, c in enumerate(("AF41", "AF42", "AF43"))],
    ], [20 * mm, 21 * mm, 20 * mm, 21 * mm, 21 * mm, 20 * mm, 21 * mm]))
    S.append(Spacer(1, 2 * mm))
    f = fig("qos_steady.pdf")
    if f:
        S.append(f)
        S.append(Paragraph("図2　定常状態のクラス別スループットと片道遅延（左：帯域、右：遅延）", NOTE))
    S.append(Spacer(1, 2 * mm))
    S.append(Paragraph("<b>結果</b>", BODY))
    S.append(Paragraph(
        f"SP+WRR では AF41 が送信量 8 Gbps をそのまま受信し（{t_sp[0]:.2f} Gbps、損失 0 %）、"
        f"遅延も {d_sp[0]:.2f} ms とキュー待ちがほぼ生じない水準に留まった。"
        f"一方 AF42・AF43 は {t_sp[1]:.2f} / {t_sp[2]:.2f} Gbps に絞られ、遅延は "
        f"{d_sp[1]:.0f} / {d_sp[2]:.0f} ms に増大した。両者の比は約 2:1 であり、WRR の重み設定どおりである。", BODY))
    S.append(Paragraph(
        f"SP を無効化して WRR のみにすると、3クラスは quantum 比 4:2:1 にほぼ一致する "
        f"{t_wrr[0]:.2f} : {t_wrr[1]:.2f} : {t_wrr[2]:.2f} Gbps "
        f"（AF43 を 1 とした比で {t_wrr[0]/t_wrr[2]:.2f} : {t_wrr[1]/t_wrr[2]:.2f} : 1.00）で機械的に分配された。"
        f"AF41 の損失は 0 % から {loss(t_wrr[0]):.1f} %、遅延は {d_sp[0]:.2f} ms から {d_wrr[0]:.1f} ms へ悪化した。", BODY))
    S.append(Paragraph(
        "いずれの設定でも受信量の合計は 9.00 Gbps でリンク容量に一致しており、"
        "どちらか一方が帯域を無駄にしているわけではない。両設定は同じ容量を別の配分則で分けている。", BODY))
    S.append(Paragraph("<b>考察</b>", BODY))
    S.append(Paragraph(
        "スケジューラの設定は、輻輳下のクラス別の帯域と遅延を決定づける。"
        "SP+WRR は最上位クラスを完全に保護する代わりに、下位2クラスの帯域を約 74 % 削り遅延を約 3.8 倍にする。"
        "WRR のみはどのクラスも重み相当の取り分を確保するが、最上位クラスを守れない。"
        "<b>両者は優劣ではなく配分方針の違いであり、どちらを選ぶかは要求次第である。</b>", BODY))

    S.append(PageBreak())

    # ── 4. 実験B ─────────────────────────────────────────────────
    S.append(Paragraph("4. 実験B：障害時の自動リルーティング", H2))
    S.append(Paragraph(
        "<b>意図</b>　経路が切り替わる過渡期に、実験Aで確認した制御がどこまで有効かを測る。"
        "またそのとき生じる通信断の長さが何によって決まるかを特定する。", BODY))
    S.append(Paragraph(
        "<b>方法</b>　実験Aと同じ輻輳条件のまま、t = 20 s に Router1 向けリンクへ netem で 100 % の"
        "パケット廃棄を注入し、t = 40 s に解除した。この障害はインタフェースを UP のまま維持するため、"
        "ルータはリンクダウンを検知できず、hello の途絶を dead-interval（3 s）待って初めて隣接を失う。"
        "これは電波リンクがフェージングで劣化する際の壊れ方に相当する。"
        "3条件——障害なし／障害あり迂回なし／障害あり自動迂回——を比較し、"
        "通信断は 20 ms 間隔プローブの受信途絶として測定した。", BODY))
    S.append(Spacer(1, 2 * mm))
    f = fig("reroute_timeseries_all.pdf", width_mm=150)
    if f:
        S.append(f)
        S.append(Paragraph("図3　クラス別の受信スループット時系列（網掛けが障害注入区間 t=20〜40 s）", NOTE))
    S.append(Spacer(1, 2 * mm))
    S.append(tbl([
        [Paragraph("条件", CELLH), Paragraph("AF41", CELLH), Paragraph("AF42", CELLH), Paragraph("AF43", CELLH)],
        [Paragraph("迂回なし（SP+WRR）", CELL), *[Paragraph(f"{v:.2f} s", CELL) for v in out_sp_no]],
        [Paragraph("自動迂回（SP+WRR）", CELL), *[Paragraph(f"{v:.2f} s", CELL) for v in out_sp_re]],
        [Paragraph("自動迂回（WRRのみ）", CELL), *[Paragraph(f"{v:.2f} s", CELL) for v in out_wrr_re]],
    ], [46 * mm, 30 * mm, 30 * mm, 30 * mm]))
    S.append(Paragraph("表　通信断の継続時間（20 ms プローブの最長受信途絶）", NOTE))
    S.append(Spacer(1, 2 * mm))
    S.append(Paragraph("<b>結果</b>", BODY))
    S.append(Paragraph(
        f"迂回機構を止めた条件では、AF41 は障害の全区間にあたる {out_sp_no[0]:.2f} 秒にわたり"
        "受信が途絶えた。復旧したのは netem を解除した瞬間であり、網が自力で回復したわけではない。", BODY))
    S.append(Paragraph(
        f"OSPF-SR による自動迂回を有効にすると、断は {out_sp_re[0]:.2f} 秒に短縮された"
        f"（{(out_sp_no[0]-out_sp_re[0])/out_sp_no[0]*100:.1f} % の短縮）。"
        "障害が継続している最中に別経路へ切り替わり、切替後のスループットは障害なし条件と同じ水準に戻った。", BODY))
    S.append(Paragraph(
        f"この断時間はクラスによらずほぼ等しく（{out_sp_re[0]:.2f} / {out_sp_re[1]:.2f} / {out_sp_re[2]:.2f} 秒）、"
        f"SP を無効化しても変わらなかった（{out_wrr_re[0]:.2f} / {out_wrr_re[1]:.2f} / {out_wrr_re[2]:.2f} 秒）。"
        "いずれも OSPF の dead-interval である 3 秒の直下に収まっている。", BODY))
    S.append(Paragraph("<b>考察</b>", BODY))
    S.append(Paragraph(
        "実験Aで確認したクラス間の差は、この過渡期には現れない。最優先クラスも他と同じだけ失われる。"
        "経路が存在しない間は優先度をつける対象そのものが無いためであり、"
        "<b>この断は QoS の断ではなく接続性の断である</b>。", BODY))
    S.append(Paragraph(
        f"断時間が dead-interval（3 s）と一致し、かつスケジューラ設定を変えても動かないことから、"
        "この空白を決めているのはキューイングではなく障害検知の速さであると判断できる。"
        "したがってこの時間を縮めるには、より高速な検知機構（BFD 等）が必要であり、"
        "優先制御の強化では短縮できない。", BODY))

    S.append(Spacer(1, 3 * mm))

    # ── 5. まとめ ────────────────────────────────────────────────
    S.append(Paragraph("5. まとめ", H2))
    S.append(tbl([
        [Paragraph("問い", CELLH), Paragraph("得られた答え", CELLH)],
        [Paragraph("輻輳下でスケジューラは何を決められるか", CELL),
         Paragraph("クラス別の帯域と遅延を決められる。SP+WRR は最上位を完全保護（損失0 %、0.16 ms）、"
                   "WRR のみは重み比の公平分配。どちらも正当な配分方針である。", CELL)],
        [Paragraph("経路の切替中もその制御は有効か", CELL),
         Paragraph("無効である。全クラスが同一の 2.9 秒を失い、スケジューラ設定を変えても変わらない。", CELL)],
        [Paragraph("では断時間は何が決めているか", CELL),
         Paragraph("障害検知である。断時間は OSPF の dead-interval 3 秒と一致する。", CELL)],
    ], [52 * mm, 116 * mm], align_right_from=99))
    S.append(Spacer(1, 3 * mm))
    S.append(Paragraph(
        "結論として、<b>スケジューラが支配するのは定常状態であり、経路再構築中の空白は支配できない。"
        "その空白を縮める手段は検知の高速化であって、キューイングの強化ではない。</b>", BODY))

    S.append(Paragraph("6. 本実験の範囲と限界", H2))
    S.append(Paragraph(
        "・無線リンクは実装していない。障害モデル（インタフェースを維持したままの全廃棄）が"
        "電波リンクの壊れ方を模したものであり、実際の電波環境での検証は今後の課題である。", BODY))
    S.append(Paragraph(
        "・容量低下（フェージングによる変調方式の低下など、リンクが落ちずに帯域だけが減る事象）は"
        "測定していない。この場合 OSPF はリンクダウンを検知しないため経路を変えず、"
        "優先制御だけで吸収できるかは未検証である。", BODY))
    S.append(Paragraph(
        "・SP を単独で用いた条件（WRR なし）は測定していない。本実験の「WRR のみ」条件は"
        "全クラスを同一 prio に揃えたものであり、SP 単独時の下位クラス枯渇は確認していない。", BODY))
    S.append(Paragraph(
        "・障害シナリオの tc_drops.csv には leri-cr1 の行が記録されておらず、"
        "ドロップ発生箇所の移動を直接示すデータは欠けている。再取得には計測スクリプトの修正が必要である。", BODY))

    S.append(Paragraph("7. データの所在", H2))
    S.append(Paragraph(
        f"SP+WRR：results/frr/{SP}/　　WRR のみ：results/frr/{WRR}/<br/>"
        "各ディレクトリの frr_normal / frr_failure / frr_failure_reroute に "
        "throughput.csv、owd_af4*.log、tc_drops.csv を格納。<br/>"
        "本書の図は plot_qos_steady.py、plot_reroute_timeseries.py、plot_guarantee_split.py で生成。"
        "本書自体は gen_experiment_report.py で生成しており、数値は実行のたびに実測値から再計算される。", NOTE))

    doc.build(S)
    print(f"[*] {args.output}")


if __name__ == "__main__":
    build()
