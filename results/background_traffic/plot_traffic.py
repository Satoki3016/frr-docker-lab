#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
研究背景用: 我が国の固定通信・移動通信トラヒック推移（総務省）
Background figures: fixed / mobile Internet traffic in Japan (MIC).

データ / Data:
  固定 fixed : gt010108.xlsx 「我が国のインターネットにおけるトラヒックの集計・試算」
              注記(B57): in=upload, out=download
              ISP9社 C/D(3/4) 2017-2025, ISP5社 Q/R(17/18) 2004-2018
  移動 mobile: gt010602.xlsx 「我が国の移動通信トラヒックの現状」
              横持ち: 行2=年月, 行4=Up/Down, 行5=平均(Gbps), 四半期 2010-2025

出力 / Output:  ja/ (日本語) と en/ (English) に同名の図を生成。
  fixed_traffic_download_upload.{png,pdf}
  mobile_traffic_download_upload.{png,pdf}
  fixed_mobile_combined.{png,pdf}
  traffic_values.csv (ja/ にのみ)
"""
import os
from datetime import date
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.dates as mdates
import numpy as np
import openpyxl

matplotlib.rcParams["axes.unicode_minus"] = False
JP_FONT = next((_f for _f in ["Noto Sans CJK JP", "TakaoPGothic", "IPAPGothic", "VL PGothic"]
                if any(_f.lower() in p.name.lower() for p in fm.fontManager.ttflist)), "sans-serif")
EN_FONT = "DejaVu Sans"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
XLSX_FIXED = os.path.join(ROOT, "gt010108.xlsx")
XLSX_MOBILE = os.path.join(ROOT, "gt010602.xlsx")

MONTHS = {"1月": 1, "01月": 1, "2月": 2, "02月": 2, "3月": 3, "03月": 3,
          "4月": 4, "04月": 4, "5月": 5, "05月": 5, "6月": 6, "06月": 6,
          "7月": 7, "07月": 7, "8月": 8, "08月": 8, "9月": 9, "09月": 9,
          "10月": 10, "11月": 11, "12月": 12}

C_FIX_D, C_FIX_U = "#1f5fa8", "#5b9bd5"   # 固定 down / up
C_MOB_D, C_MOB_U = "#c0392b", "#e59866"   # 移動 down / up

# 主要サービス等の「日本での開始年月」 (year, month, ja_label, en_label)
# いずれも日本準拠の時期のため、英語ラベルには (Japan) を付す
EVENTS = [
    (2007, 6,  "YouTube",        "YouTube (Japan)"),
    (2008, 4,  "Twitter/X",  "Twitter/X (Japan)"),
    (2008, 7,  "iPhone",         "iPhone (Japan)"),
    (2011, 6,  "LINE",           "LINE (Japan)"),
    (2014, 2,  "Instagram",      "Instagram (Japan)"),
    (2016, 8,  "DAZN",           "DAZN (Japan)"),
    (2020, 1,  "COVID-19",       "COVID-19 (Japan)"),
    (2022, 11, "ChatGPT",        "ChatGPT"),   # 世界同時公開のため (Japan) は付けない
]


def load_fixed(col_up, col_down):
    ws = openpyxl.load_workbook(XLSX_FIXED, data_only=True)[
        "我が国のインターネットにおけるトラヒックの集計・試算"]
    cur_year, dates, up, down = None, [], [], []
    for r in range(7, ws.max_row + 1):
        y = ws.cell(r, 1).value
        if isinstance(y, str) and "年" in y:
            try:
                cur_year = int(y.replace("年", ""))
            except ValueError:
                pass
        mo = ws.cell(r, 2).value
        u, d = ws.cell(r, col_up).value, ws.cell(r, col_down).value
        if cur_year and isinstance(mo, str) and mo in MONTHS \
                and isinstance(u, (int, float)) and isinstance(d, (int, float)):
            dates.append(date(cur_year, MONTHS[mo], 1))
            up.append(u / 1000.0)
            down.append(d / 1000.0)
    return dates, up, down


def splice_fixed(d5, u5, dn5, d9, u9, dn9):
    cut = min(d9)
    dates, up, down = [], [], []
    for dt, u, dn in zip(d5, u5, dn5):
        if dt < cut:
            dates.append(dt); up.append(u); down.append(dn)
    for dt, u, dn in zip(d9, u9, dn9):
        dates.append(dt); up.append(u); down.append(dn)
    return dates, up, down


def _num(v):
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", "").strip())
        except ValueError:
            return None
    return None


def _mobile_dates(ws):
    """(column, date) のリストを返す。列は各日付の Up 列(奇数)。"""
    out = []
    for cc in range(3, ws.max_column + 1, 2):
        lbl = ws.cell(2, cc).value
        if not isinstance(lbl, str) or "年" not in lbl:
            continue
        try:
            yr = int(lbl.split("年")[0])
            mtxt = lbl.split("年")[1].replace("分", "")
        except (ValueError, IndexError):
            continue
        mo = MONTHS.get(mtxt)
        if mo is None:
            continue
        out.append((cc, date(yr, mo, 1)))
    return out


def load_mobile():
    """行5=平均(Gbps) を Tbps で返す。return dates, up, down"""
    ws = openpyxl.load_workbook(XLSX_MOBILE, data_only=True)["集計情報"]
    dates, up, down = [], [], []
    for cc, dt in _mobile_dates(ws):
        u, d = _num(ws.cell(5, cc).value), _num(ws.cell(5, cc + 1).value)
        if u is None or d is None:
            continue
        dates.append(dt)
        up.append(u / 1000.0)
        down.append(d / 1000.0)
    return dates, up, down


def load_mobile_extra():
    """移動通信の契約数(行8)と、総務省公表の「1契約当たり 月間延べ(MB)」(行11)。
    行11は Up(cc) / Down(cc+1)。GBに換算して返す。
    return dates, contracts_million, persub_down_GB, persub_up_GB"""
    ws = openpyxl.load_workbook(XLSX_MOBILE, data_only=True)["集計情報"]
    dates, contracts, ps_dl, ps_ul = [], [], [], []
    for cc, dt in _mobile_dates(ws):
        n = _num(ws.cell(8, cc).value)              # 契約数
        up_mb = _num(ws.cell(11, cc).value)         # 1契約当たり月間延べ Up [MB]（公表値）
        dn_mb = _num(ws.cell(11, cc + 1).value)     # 1契約当たり月間延べ Down [MB]（公表値）
        if n is None or n <= 0 or up_mb is None or dn_mb is None:
            continue
        dates.append(dt)
        contracts.append(n / 1e6)                    # 百万契約
        ps_dl.append(dn_mb / 1000.0)                 # MB -> GB
        ps_ul.append(up_mb / 1000.0)
    return dates, contracts, ps_dl, ps_ul


# ---- language label packs ----
L = {
    "ja": {
        "font": JP_FONT,
        "ylabel": "平均トラヒック [Tbps]",
        "xlabel": "年",
        "fix_title": "固定通信（ブロードバンド）の総トラヒック推移\n"
                     "（総務省 我が国のインターネットにおけるトラヒックの集計・試算）",
        "mob_title": "移動通信の月間平均トラヒック推移\n（総務省 我が国の移動通信トラヒックの現状）",
        "cmb_title": "我が国の固定通信・移動通信トラヒックの推移（総務省）",
        "cmb_ev_title": "我が国の固定通信・移動通信トラヒックの推移と主要サービスの国内開始時期（総務省）",
        "fix_dl5": "ダウンロード（協力ISP5社推計, 2004–2018）",
        "fix_ul5": "アップロード（協力ISP5社推計）",
        "fix_dl9": "ダウンロード（協力ISP9社推計, 2017–2025）",
        "fix_ul9": "アップロード（協力ISP9社推計）",
        "change": "推計方法変更\n（協力ISP 5社→9社）",
        "mob_dl": "ダウンロード (Down)",
        "mob_ul": "アップロード (Up)",
        "cmb_fd": "固定 ダウンロード", "cmb_fu": "固定 アップロード",
        "cmb_md": "移動 ダウンロード", "cmb_mu": "移動 アップロード",
        "con_title": "移動通信の契約数の推移（総務省）",
        "con_ylabel": "契約数 [百万契約]",
        "ps_title": "移動通信の1契約あたり月間トラフィックの推移（総務省）",
        "ps_ylabel": "1契約あたり月間トラフィック [GB/月]",
        "ps_dl": "ダウンロード", "ps_ul": "アップロード",
        "conv_title": "移動通信：契約数と1契約あたり月間トラフィック（総務省）",
        "conv_con": "契約数（左軸）",
        "conv_ps": "1契約あたりDL（右軸）",
    },
    "en": {
        "font": EN_FONT,
        "ylabel": "Average traffic [Tbps]",
        "xlabel": "Year",
        "fix_title": "Fixed broadband traffic in Japan\n"
                     "(MIC national estimate of Internet traffic)",
        "mob_title": "Mobile traffic in Japan\n(MIC, monthly average)",
        "cmb_title": "Fixed and mobile Internet traffic in Japan (MIC)",
        "cmb_ev_title": "Fixed and mobile Internet traffic in Japan with launch timing of major services (MIC)",
        "fix_dl5": "Download (5-ISP estimate, 2004–2018)",
        "fix_ul5": "Upload (5-ISP estimate)",
        "fix_dl9": "Download (9-ISP estimate, 2017–2025)",
        "fix_ul9": "Upload (9-ISP estimate)",
        "change": "Estimation method changed\n(cooperating ISPs: 5 -> 9)",
        "mob_dl": "Download",
        "mob_ul": "Upload",
        "cmb_fd": "Fixed download", "cmb_fu": "Fixed upload",
        "cmb_md": "Mobile download", "cmb_mu": "Mobile upload",
        "con_title": "Mobile subscriptions in Japan (MIC)",
        "con_ylabel": "Subscriptions [million]",
        "ps_title": "Monthly mobile traffic per subscription in Japan (MIC)",
        "ps_ylabel": "Traffic per subscription [GB/month]",
        "ps_dl": "Download", "ps_ul": "Upload",
        "conv_title": "Mobile: subscriptions and per-subscription traffic (MIC)",
        "conv_con": "Subscriptions (left)",
        "conv_ps": "Per-subscription DL (right)",
    },
}


def _year_ticks(ax, dts, step=2):
    """目盛りは各年1月に固定（ラベル年=その年の1月を正しく指す）。
    最終データ年から step 年刻みで遡って年を選び、終端が切れないよう
    右端を最終データの翌1月まで伸ばす。"""
    y_last, y_first = dts[-1].year, dts[0].year
    years = list(range(y_last, y_first - 1, -step))[::-1]
    if years[-1] < y_last:          # 最終年が刻みから漏れる場合に備える
        years.append(y_last)
    ax.set_xticks([date(y, 1, 1) for y in years])
    ax.set_xticklabels([str(y) for y in years])
    ax.set_xlim(date(y_first, 1, 1), date(y_last + 1, 1, 1))
    ax.set_autoscalex_on(False)     # 後続の margins() で xlim が戻らないよう固定


def build(lang, data, outdir):
    t = L[lang]
    matplotlib.rcParams["font.family"] = t["font"]
    (d5, u5, dn5), (d9, u9, dn9), (fd, fu, fdn), (md, mu, mdn), \
        (dc, con, ps_dl, ps_ul) = data
    cut = min(d9)
    os.makedirs(outdir, exist_ok=True)

    def finish(ax, title, dts):
        ax.set_ylabel(t["ylabel"], fontsize=11)
        ax.set_xlabel(t["xlabel"], fontsize=11)
        ax.set_title(title, fontsize=11, fontweight="bold")
        ax.grid(True, ls="--", lw=0.5, alpha=0.6)
        _year_ticks(ax, dts)

    def save(fig, name):
        for ext in ("png", "pdf"):
            p = os.path.join(outdir, f"{name}.{ext}")
            fig.savefig(p, bbox_inches="tight")
            print("WROTE", p)
        plt.close(fig)

    # 1) fixed only (ISP5 + ISP9)
    fig, ax = plt.subplots(figsize=(8.6, 4.8), dpi=150)
    ax.plot(d5, dn5, "--o", ms=3.5, lw=1.6, color=C_FIX_D, alpha=0.55,
            markerfacecolor="white", label=t["fix_dl5"])
    ax.plot(d5, u5, "--s", ms=3.2, lw=1.6, color=C_FIX_U, alpha=0.55,
            markerfacecolor="white", label=t["fix_ul5"])
    ax.plot(d9, dn9, "-o", ms=4.5, lw=2.2, color=C_FIX_D, label=t["fix_dl9"])
    ax.plot(d9, u9, "-s", ms=4, lw=2.0, color=C_FIX_U, label=t["fix_ul9"])
    ax.axvline(cut, color="#888888", ls=":", lw=1.2)
    ax.annotate(t["change"], (cut, max(dn9) * 0.62), xytext=(-6, 0),
                textcoords="offset points", ha="right", fontsize=8, color="#555555")
    ax.set_ylim(0, max(dn9) * 1.18)
    finish(ax, t["fix_title"], [d5[0], d9[-1]])
    ax.legend(loc="upper left", framealpha=0.9, fontsize=8.2)
    fig.tight_layout()
    save(fig, "fixed_traffic_download_upload")

    # 2) mobile only
    fig, ax = plt.subplots(figsize=(8.0, 4.6), dpi=150)
    ax.plot(md, mdn, "-o", ms=3.5, lw=2, color=C_MOB_D, label=t["mob_dl"])
    ax.plot(md, mu, "-s", ms=3.2, lw=2, color=C_MOB_U, label=t["mob_ul"])
    ax.set_ylim(0, max(mdn) * 1.15)
    finish(ax, t["mob_title"], md)
    ax.legend(loc="upper left", framealpha=0.9, fontsize=10)
    fig.tight_layout()
    save(fig, "mobile_traffic_download_upload")

    # 3) combined 4 series
    fig, ax = plt.subplots(figsize=(8.6, 5.0), dpi=150)
    ax.plot(fd, fdn, "-o", ms=4.5, lw=2.2, color=C_FIX_D, label=t["cmb_fd"])
    ax.plot(fd, fu, "-s", ms=4, lw=2.0, color=C_FIX_U, label=t["cmb_fu"])
    ax.plot(md, mdn, "--^", ms=3.8, lw=2.2, color=C_MOB_D, label=t["cmb_md"])
    ax.plot(md, mu, "--D", ms=3.2, lw=2.0, color=C_MOB_U, label=t["cmb_mu"])
    ax.set_ylim(0, max(max(fdn), max(mdn)) * 1.15)
    finish(ax, t["cmb_title"], [fd[0], fd[-1]])
    ax.legend(loc="upper left", framealpha=0.9, fontsize=10, ncol=2)
    fig.tight_layout()
    save(fig, "fixed_mobile_combined")

    # 4) combined + イベント矢印注記（類似グラフ）
    #    矢印の先は固定通信ダウンロード曲線上の該当時期の値を指す
    ev_idx = 2 if lang == "ja" else 3   # EVENTS: (year, month, ja_label, en_label)
    fig, ax = plt.subplots(figsize=(11.0, 6.2), dpi=150)
    ax.plot(fd, fdn, "-o", ms=4.5, lw=2.2, color=C_FIX_D, label=t["cmb_fd"])
    ax.plot(fd, fu, "-s", ms=4, lw=2.0, color=C_FIX_U, label=t["cmb_fu"])
    ax.plot(md, mdn, "--^", ms=3.8, lw=2.2, color=C_MOB_D, label=t["cmb_md"])
    ax.plot(md, mu, "--D", ms=3.2, lw=2.0, color=C_MOB_U, label=t["cmb_mu"])
    ymax = max(max(fdn), max(mdn)) * 1.60
    ax.set_ylim(0, ymax)

    # 固定DL曲線を補間して各イベント時期の値(=矢印の先)を求める
    _xnum = mdates.date2num(fd)
    # 時期が密集する先頭3件(YouTube/Twitter/iPhone)は左の空き領域へラベルを退避し、
    # 折れ矢印で本来の時期(曲線上)を指す。残りは真上に直線矢印。
    CLUSTER = {0, 1, 2}
    cluster_lx = date(2004, 10, 1)              # ラベル退避先(左端の空き)
    cluster_ly = [0.93, 0.80, 0.67]             # 3件を縦に段違い配置
    levels = [0.93, 0.82, 0.71, 0.60]           # 非密集イベントの高さ循環
    for i, ev in enumerate(EVENTS):
        yr, mo = ev[0], ev[1]
        lbl = ev[ev_idx]
        x = date(yr, mo, 1)
        y_curve = float(np.interp(mdates.date2num(x), _xnum, fdn))  # 固定DL曲線上の値
        if i in CLUSTER:
            # 英語版は "(Japan)" を2行目に折り返してラベル幅を詰め、
            # 日本語版と同じく折れ矢印の水平部を長く見せる
            disp = lbl.replace(" (Japan)", "\n(Japan)") if lang == "en" else lbl
            ax.annotate(
                disp, xy=(x, y_curve), xytext=(cluster_lx, ymax * cluster_ly[i]),
                ha="left", va="center", fontsize=13, color="black", fontweight="bold",
                arrowprops=dict(arrowstyle="->", color="black", lw=1.4,
                                shrinkA=6, shrinkB=2,
                                connectionstyle="angle,angleA=0,angleB=90,rad=6"),
                zorder=6)
        else:
            ax.annotate(
                lbl, xy=(x, y_curve), xytext=(x, ymax * levels[i % len(levels)]),
                ha="center", va="bottom", fontsize=13, color="black", fontweight="bold",
                arrowprops=dict(arrowstyle="->", color="black", lw=1.4,
                                shrinkA=4, shrinkB=2), zorder=6)
    finish(ax, t["cmb_ev_title"], [fd[0], fd[-1]])
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12),
              framealpha=0.95, fontsize=11, ncol=4)
    fig.tight_layout()
    save(fig, "fixed_mobile_combined_events")

    # 5) 移動通信の契約数（有無線融合の必要性: 無線接続デバイスの激増）
    fig, ax = plt.subplots(figsize=(8.0, 4.6), dpi=150)
    ax.plot(dc, con, "-o", ms=3.5, lw=2, color=C_MOB_D)
    ax.fill_between(dc, con, color=C_MOB_D, alpha=0.10)
    ax.set_ylabel(t["con_ylabel"], fontsize=11)
    ax.set_xlabel(t["xlabel"], fontsize=11)
    ax.set_title(t["con_title"], fontsize=11, fontweight="bold")
    ax.grid(True, ls="--", lw=0.5, alpha=0.6)
    ax.set_ylim(0, max(con) * 1.12)
    _year_ticks(ax, dc)
    ax.margins(x=0.02)
    fig.tight_layout()
    save(fig, "mobile_subscriptions")

    # 6) 1契約あたり月間トラフィック（1台あたりの使用量も増大）
    fig, ax = plt.subplots(figsize=(8.0, 4.6), dpi=150)
    ax.plot(dc, ps_dl, "-o", ms=3.5, lw=2, color=C_MOB_D, label=t["ps_dl"])
    ax.plot(dc, ps_ul, "-s", ms=3.2, lw=2, color=C_MOB_U, label=t["ps_ul"])
    ax.set_ylabel(t["ps_ylabel"], fontsize=11)
    ax.set_xlabel(t["xlabel"], fontsize=11)
    ax.set_title(t["ps_title"], fontsize=11, fontweight="bold")
    ax.grid(True, ls="--", lw=0.5, alpha=0.6)
    ax.set_ylim(0, max(ps_dl) * 1.15)
    _year_ticks(ax, dc)
    ax.margins(x=0.02)
    ax.legend(loc="upper left", framealpha=0.9, fontsize=10)
    fig.tight_layout()
    save(fig, "mobile_traffic_per_subscription")

    # 7) 契約数 + 1契約あたりDL を左右2軸で1枚に統合（スライド1枚用）
    c_con, c_ps = "#c0392b", "#1f5fa8"
    fig, ax1 = plt.subplots(figsize=(8.4, 4.8), dpi=150)
    l1, = ax1.plot(dc, con, "-o", ms=3.5, lw=2.2, color=c_con, label=t["conv_con"])
    ax1.set_ylabel(t["con_ylabel"], fontsize=11, color=c_con)
    ax1.tick_params(axis="y", labelcolor=c_con)
    ax1.set_ylim(0, max(con) * 1.12)
    ax1.set_xlabel(t["xlabel"], fontsize=11)
    ax1.grid(True, ls="--", lw=0.5, alpha=0.6)
    _year_ticks(ax1, dc)
    ax1.margins(x=0.02)
    ax2 = ax1.twinx()
    l2, = ax2.plot(dc, ps_dl, "-s", ms=3.2, lw=2.2, color=c_ps, label=t["conv_ps"])
    ax2.set_ylabel(t["ps_ylabel"], fontsize=11, color=c_ps)
    ax2.tick_params(axis="y", labelcolor=c_ps)
    ax2.set_ylim(0, max(ps_dl) * 1.15)
    ax2.spines["top"].set_visible(False)
    ax1.set_title(t["conv_title"], fontsize=11, fontweight="bold")
    ax1.legend(handles=[l1, l2], loc="upper left", framealpha=0.9, fontsize=10)
    fig.tight_layout()
    save(fig, "mobile_convergence")


def main():
    d9, u9, dn9 = load_fixed(3, 4)
    d5, u5, dn5 = load_fixed(17, 18)
    fd, fu, fdn = splice_fixed(d5, u5, dn5, d9, u9, dn9)
    md, mu, mdn = load_mobile()
    dc, con, ps_dl, ps_ul = load_mobile_extra()
    data = ((d5, u5, dn5), (d9, u9, dn9), (fd, fu, fdn), (md, mu, mdn),
            (dc, con, ps_dl, ps_ul))

    build("ja", data, os.path.join(HERE, "ja"))
    build("en", data, os.path.join(HERE, "en"))

    # CSV (数値は言語非依存なので ja/ に1つ)
    csv = os.path.join(HERE, "ja", "traffic_values.csv")
    with open(csv, "w", encoding="utf-8") as f:
        f.write("category,date,download_Tbps,upload_Tbps\n")
        for dt, u, d in zip(d5, u5, dn5):
            f.write(f"fixed_isp5,{dt.isoformat()},{d:.4f},{u:.4f}\n")
        for dt, u, d in zip(d9, u9, dn9):
            f.write(f"fixed_isp9,{dt.isoformat()},{d:.4f},{u:.4f}\n")
        for dt, u, d in zip(md, mu, mdn):
            f.write(f"mobile,{dt.isoformat()},{d:.4f},{u:.4f}\n")
    print("WROTE", csv)

    print(f"\n[fixed ISP5] {d5[0]}–{d5[-1]}  DL {dn5[0]:.2f}->{dn5[-1]:.1f} Tbps")
    print(f"[fixed ISP9] {d9[0]}–{d9[-1]}  DL {dn9[0]:.1f}->{dn9[-1]:.1f} Tbps")
    print(f"[mobile]     {md[0]}–{md[-1]}  DL {mdn[0]:.2f}->{mdn[-1]:.1f} Tbps")


if __name__ == "__main__":
    main()
