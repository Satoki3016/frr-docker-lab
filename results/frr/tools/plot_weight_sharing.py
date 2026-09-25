#!/usr/bin/env python3
"""動的制御 → te_monitor の重み共有 (案A) の実機検証を1枚にまとめる。

入力 (radwin_experiment.sh control の結果フォルダ):
  controller.csv   制御の判断 (絶対時刻, 約2秒周期)
  te_monitor.log   /tmp/frr_te_monitor.log の写し (時刻は秒単位の壁時計)

(a) 制御の入力と出力: 各ホップの PHY レート, 推定容量, 適用した整形レート
(b) CR1 に振り分ける割合 w1/(w1+w2+w3): 制御が公開した値と te_monitor が経路表に書いた値
(c) 反映遅れ: 制御が重みを変えてから te_monitor が経路表を書くまで
    (te_monitor の時刻は秒の切り捨てなので、遅れは幅1秒の区間で示す)

使い方: python3 results/frr/tools/plot_weight_sharing.py --dir 20260925_success_control_wcmp_01
"""
from __future__ import annotations
import argparse, csv, re, sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from result_paths import result_dir  # noqa: E402
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.font_manager as fm

for _f in ["Noto Sans CJK JP", "TakaoPGothic", "IPAPGothic"]:
    if any(_f.lower() in p.name.lower() for p in fm.fontManager.ttflist):
        matplotlib.rcParams["font.family"] = _f; break
matplotlib.rcParams.update({
    "figure.facecolor":"white","axes.facecolor":"white",
    "axes.spines.top":False,"axes.spines.right":False,"axes.linewidth":0.8,
    "axes.labelsize":9,"axes.titlesize":9,"axes.titlepad":4,"axes.labelpad":3,
    "xtick.labelsize":8,"ytick.labelsize":8,"legend.fontsize":8,
    "xtick.major.width":0.8,"ytick.major.width":0.8,
    "legend.framealpha":0.95,"legend.edgecolor":"0.8"})

CH1, CH2 = "#009E73", "#CC79A7"          # ホップ1, ホップ2
CEST, CAPP = "#E69F00", "#0072B2"        # 推定容量, 整形レート
CCTL, CTE = "#0072B2", "#D55E00"         # 制御の公開値, te_monitor の経路表

# CR1 が行に無いのは OSPF 隣接の消失で外した場合。重み 0 (除外) として扱う。
ROUTE_RE = re.compile(r"^\[(\d\d:\d\d:\d\d)\] 経路更新 \[wcmp\]:(?: CR1\(w=(\d+)(?::除外)?\))? CR2\(w=(\d+)\) CR3\(w=(\d+)\)")
START_RE = re.compile(r"^\[(\d\d:\d\d:\d\d)\] === OSPF-SR TE Monitor 起動")


def load_controller(path):
    rows = list(csv.DictReader(path.open()))
    return [{"t": float(r["time"]), "phy1": float(r["hop1_phy"]), "phy2": float(r["hop2_phy"]),
             "est": float(r["est_mbps"]), "app": float(r["applied_mbps"]),
             "w1": int(r["w1"]), "action": r["action"]} for r in rows]


def load_te_routes(path, day):
    """最後に起動した te_monitor の経路更新だけを (壁時計[s], w1, w2, w3) で返す。"""
    lines = path.read_text(errors="replace").splitlines()
    head = max(i for i, s in enumerate(lines) if START_RE.match(s))
    out = []
    for s in lines[head:]:
        m = ROUTE_RE.match(s)
        if m:
            hh, mm, ss = map(int, m.group(1).split(":"))
            t = day.replace(hour=hh, minute=mm, second=ss).timestamp()
            out.append((t, *(int(g) if g is not None else 0 for g in m.groups()[1:])))
    return out


def share(w1, w2, w3):
    return 100.0 * w1 / (w1 + w2 + w3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="結果フォルダ (タグ名または results/frr からの相対パス)")
    ap.add_argument("--out", default=None, help="出力パス (拡張子なし)")
    a = ap.parse_args()
    D = result_dir(a.dir)
    C = load_controller(D / "controller.csv")
    t0 = C[0]["t"]
    day = datetime.fromtimestamp(t0).replace(microsecond=0)
    R = load_te_routes(D / "te_monitor.log", day)

    # 制御の公開値: 各サンプルで (w1, 100, 100)。停止 (最後のサンプル) 以降は公開なし。
    ct = [r["t"] - t0 for r in C]
    t_stop = ct[-1]
    ctl_share = [share(r["w1"], 100, 100) for r in C]
    rt = [x[0] - t0 for x in R]
    te_share = [share(*x[1:]) for x in R]

    x_lo, x_hi = min(rt[0], 0) - 5, max(rt[-1], t_stop) + 15

    # 反映遅れ: 制御が重みを変えたサンプル → 同じ重みを書いた te_monitor の経路更新。
    # te_monitor の時刻は秒の切り捨てなので、遅れは [T−c, T−c+1) の幅で決まる。
    changes = [(ct[i], C[i]["w1"], C[i]["action"]) for i in range(len(C))
               if i == 0 or C[i]["w1"] != C[i - 1]["w1"]]
    delays = []
    for tc, w1, act in changes:
        tr = next(t for t, (_, rw1, rw2, _) in zip(rt, R) if t >= tc - 1 and rw1 == w1 and rw2 == 100)
        delays.append((tc, w1, act, max(tr - tc, 0.0), tr - tc + 1))
    # 静的値へ戻った更新。te_monitor を制御と同時に止めた場合は記録が無い。
    fb = next((t for t, x in zip(rt, R) if t >= t_stop - 1 and x[2] != 100), None)

    fig, (a1, a2, a3) = plt.subplots(3, 1, figsize=(7.4, 7.2), sharex=True,
                                     gridspec_kw={"height_ratios": [1.0, 1.0, 0.55], "hspace": 0.2})
    for ax in (a1, a2, a3):
        ax.axvspan(x_lo, 0, color="#F0F0F0", zorder=0)
        ax.axvspan(t_stop, x_hi, color="#F0F0F0", zorder=0)
        ax.grid(axis="y", lw=0.4, color="0.9", zorder=0)

    # (a) 制御の入力 (PHY) と出力 (整形レート)
    g = lambda k: [r[k] / 1000 for r in C]
    a1.step(ct, g("phy1"), where="post", lw=1.0, color=CH1, label="PHY レート (ホップ1)")
    a1.step(ct, g("phy2"), where="post", lw=1.0, color=CH2, label="PHY レート (ホップ2)")
    a1.step(ct, g("est"), where="post", lw=1.3, color=CEST, label="推定容量 = 0.52 × min(PHY1, PHY2)")
    a1.step(ct, g("app"), where="post", lw=1.4, ls="--", color=CAPP, label="適用した CR1 整形レート")
    a1.set_ylabel("レート [Gbps]")
    a1.set_ylim(0, 5.6)
    a1.legend(loc="upper center", ncol=2, columnspacing=1.4)
    a1.set_title("(a) 制御の入力と出力", loc="left", fontweight="bold")

    # (b) CR1 への振り分け割合
    ctl_x = ct + [t_stop]
    a2.step(ctl_x, ctl_share + [ctl_share[-1]], where="post", lw=2.4, color=CCTL, alpha=0.45,
            label="制御が公開した重み (weights.env)")
    # te_monitor も止めた場合、停止後の経路表は記録が無いので線を伸ばさない
    te_end = x_hi if fb is not None else t_stop
    a2.step(rt + [te_end], te_share + [te_share[-1]], where="post", lw=1.2, color=CTE)
    a2.plot(rt, te_share, "o", ms=3.2, color=CTE, zorder=4)
    a2.plot([], [], "-o", lw=1.2, ms=3.2, color=CTE, label="te_monitor が経路表に書いた重み (点 = 書き込み)")
    a2.set_ylabel("CR1 への振り分け割合 [%]")
    a2.set_ylim(0, 14)
    a2.legend(loc="upper center", ncol=2, columnspacing=1.4)
    a2.set_title("(b) WCMP の重み (CR1 の割合 = w1 / (w1 + w2 + w3))", loc="left", fontweight="bold")
    notes = [((x_lo + 0) / 2, "制御なし\n(静的 6:25:25)")]
    notes.append(((t_stop + x_hi) / 2, "制御停止後\n(静的 6:25:25)" if fb is not None else "制御停止後\n(記録なし)"))
    for x, txt in notes:
        a2.text(x, 0.6, txt, ha="center", va="bottom", fontsize=6.5, color="#777777")

    # (c) 反映遅れ (区間 [下限, 上限])
    ev = [(tc, dlo, dhi, act) for tc, _, act, dlo, dhi in delays]
    if fb is not None:
        ev.append((t_stop, max(fb - t_stop, 0.0), fb - t_stop + 1, "停止"))
    for tc, dlo, dhi, act in ev:
        a3.vlines(tc, dlo, dhi, lw=2.6, color=CTE, zorder=3)
        # 近接する事象のラベルは上へ段違いに積み、バーの真上に置く
        near = [e for e in ev if e[0] < tc and tc - e[0] < 0.06 * (x_hi - x_lo)]
        a3.text(tc, dhi + 0.12 + 0.42 * len(near), act, ha="center", va="bottom",
                fontsize=6.5, color="0.3")
    a3.set_ylabel("反映遅れ [s]")
    a3.set_ylim(0, 4.2)
    a3.set_title("(c) 重みの変更から経路表への反映まで (区間は時刻分解能 1 s による幅)",
                 loc="left", fontweight="bold")
    a3.set_xlabel("制御開始からの経過時間 [s]")
    a3.set_xlim(x_lo, x_hi)

    out = a.out or str(D / "result_weight_sharing")
    fig.savefig(out + ".pdf", bbox_inches="tight")
    fig.savefig(out + ".png", dpi=300, bbox_inches="tight")
    print(f"出力: {out}.pdf / .png")
    for tc, w1, act, dlo, dhi in delays:
        print(f"  t={tc:6.1f}s {act:5s} w1={w1:3d} 反映遅れ {dlo:.1f}–{dhi:.1f} s")
    if fb is not None:
        print(f"  制御停止 t={t_stop:.1f}s → 静的値 {max(fb - t_stop, 0):.1f}–{fb - t_stop + 1:.1f} s")
    else:
        print("  制御停止後の静的値への復帰: 記録なし (te_monitor も停止済み)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
