#!/usr/bin/env python3
"""無線容量に追従して WCMP の重みと HTB の整形率を更新する制御ループ。

ODU の telemetry (MCS / PHY レート) から無線チェーンの実効容量を推定し、
変化が閾値を超えたら
    ・HTB の CR1 レート (leri-cr1 / cr1-lere)
    ・経路の重み (table 41/42/43 のマルチパス)
を更新する。経路選択に優先度は使わない。優先度は各リンクの HTB だけで効く。

設計上の判断:
  ・下げは即座、上げは N 回連続で確認してから。
    容量を過大評価すると無線が溢れて損失が出るため、安全側に倒す。
  ・閾値を設けてフラッピングを防ぐ。MCS は秒単位で揺れるため。
  ・重みは w2=w3=100 に固定し w1 を比例させる (Linux の weight 上限 255 に収まる)。

使い方:
    sudo python3 scripts/radwin_wcmp_controller.py             # 既定で回す
    sudo python3 scripts/radwin_wcmp_controller.py --once      # 1回だけ評価
    sudo python3 scripts/radwin_wcmp_controller.py --dry-run   # 変更せず判断だけ表示
    sudo python3 scripts/radwin_wcmp_controller.py --check     # 前提確認のみ (SSHなし)
    sudo python3 scripts/radwin_wcmp_controller.py --pprime --efficiency-table scripts/radwin_mcs_efficiency.json
        改良版 P′ (2026-10-12): (1) 容量を下げるときは、経路の重みを先に変えてから HTB を絞る
        (te_monitor の FIFO に 1 行書いて知らせ、経路表が変わったのを確かめてから)。上げるときは HTB が先。
        (2) 容量の見積もりの効率を、MCS ごとの実測値の表から読む (表にない MCS は 0.52)。

実験用の入口と保存手順: docs/radwin_experiment.md
"""
from __future__ import annotations
import argparse
import csv
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from radwin_telemetry import collect  # noqa: E402

# ── 制御パラメータ ──────────────────────────────────────────────────
INTERVAL = 2.0          # ポーリング間隔 [s]。OSPF hello=1s / dead=3s と同程度の応答性
THRESHOLD = 0.10        # この割合を超える変化で更新 (フラッピング防止)
UP_CONFIRM = 3          # 上げるときに必要な連続確認回数 (下げは即座)
DOWN_CONFIRM = 2        # 無線断とみなすのに必要な連続「未接続」回数 (1回の SSH 失敗で外さない)
MIN_MBPS = 100          # 下限。これ以下は無線がほぼ死んでいると見なす
SAFETY = 0.9            # 実容量に対する安全率 (既存の設計則と同じ)

# ── 環境 ────────────────────────────────────────────────────────────
WIRED_MBPS = 9000       # CR2 / CR3 の HTB レート
WRR = (4, 2, 1)         # AF41 : AF42 : AF43
GUARANTEE_DIV = 10      # 保証 rate を 1/10 に縮小 (SP を効かせるため)
HTB_DEVS = [("LER_Ingress", "leri-cr1"), ("CR1", "cr1-lere")]
TABLES = (41, 42, 43)
NEXTHOPS = [("10.0.1.2", "leri-cr1"), ("10.0.3.2", "leri-cr2"), ("10.0.5.2", "leri-cr3")]
LOG_CSV = "/tmp/radwin_controller.csv"

# ── frr_te_monitor.sh との重みの共有 ────────────────────────────────
# 経路表を書く主体を1つにする。te_monitor が動いている間は te_monitor だけが
# 経路表を書き、重みはこのファイルから読む。制御は重みと HTB だけを決める。
# (te_monitor はリンク断で CR1 を外すが、制御は ODU への SSH が生きていれば
#  「正常」と判断するため、制御が経路を書くと外した CR1 を復活させてしまう)
WEIGHTS_FILE = os.environ.get("RADWIN_WEIGHTS_FILE", "/run/radwin/weights.env")
# te_monitor が稼働中に書く pidfile (稼働判定に使う)
TE_PID_FILE = os.environ.get("RADWIN_TE_PID_FILE", "/run/radwin/te_monitor.pid")
# auto: te_monitor が動いていれば任せる / self: 常に自分で書く / te_monitor: 常に任せる
ROUTE_OWNER = os.environ.get("RADWIN_ROUTE_OWNER", "auto")


def sh(args: list[str]) -> tuple[int, str]:
    p = subprocess.run(args, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def get_label() -> str:
    """実際に table 41 に入っている MPLS ラベルを読む。

    frr_dscp_te.sh が OSPF から動的取得した値をそのまま使うのが正しい。
    取れなければ構成上の既定値 (SRGB 16000 + LER_Egress index 5) に落とす。
    """
    _, out = sh(["ip", "netns", "exec", "LER_Ingress",
                 "ip", "route", "show", "table", "41"])
    m = re.search(r"encap mpls (\d+)", out)
    return m.group(1) if m else "16005"


def burst_bytes(kbps: int) -> int:
    """frr_dscp_te.sh の _b() と同じ計算。"""
    return max(kbps * 1000 // 8 // 50, 8192)


def apply_htb(mbps: int) -> bool:
    """CR1 経路の HTB レートを mbps に張り替える。全コマンド成功で True。"""
    total = mbps * 1000                       # kbps
    s = sum(WRR)
    r = [total // GUARANTEE_DIV,
         total * WRR[1] // s // GUARANTEE_DIV,
         total * WRR[2] // s // GUARANTEE_DIV]
    ok = True
    for ns, dev in HTB_DEVS:
        base = ["ip", "netns", "exec", ns, "tc", "class", "change", "dev", dev]
        # ルートクラス
        cmds = [base + ["parent", "1:", "classid", "1:0", "htb",
                        "rate", f"{total}kbit", "ceil", f"{total}kbit",
                        "burst", f"{burst_bytes(total)}b",
                        "cburst", f"{burst_bytes(total)}b"]]
        # 3クラス。prio と quantum は frr_dscp_te.sh と同じ値を維持する
        for i, (cid, prio) in enumerate([("1:1", 0), ("1:2", 1), ("1:3", 1)]):
            cmds.append(base + ["parent", "1:0", "classid", cid, "htb",
                                "rate", f"{r[i]}kbit", "ceil", f"{total}kbit",
                                "burst", f"{burst_bytes(r[i])}b",
                                "cburst", f"{burst_bytes(total)}b",
                                "prio", str(prio),
                                "quantum", str(WRR[i] * 9000)])
        for c in cmds:
            code, out = sh(c)
            if code != 0:
                ok = False
                print(f"  [NG] tc {ns}/{dev} {' '.join(c[-8:])} → {out}")
    return ok


# 無線断のときの重み。w1=0 は「CR1 を経路から外す」の意味 (te_monitor も同じ解釈)。
LINK_DOWN_WEIGHTS = (0, 100, 100)


def weights_for(mbps: int) -> tuple[int, int, int]:
    """容量比から整数の重みを作る。w2=w3=100 に固定し w1 を比例させる。"""
    w1 = max(1, min(255, round(mbps / WIRED_MBPS * 100)))
    return w1, 100, 100


# ── AF41 の振り分けの判定 (条件 P3) ──────────────────────────────────
# 経路の振り分けはフロー単位のハッシュなので、CR1 に乗る AF41 のフロー数は重みどおりにならず
# ばらつく (二項分布)。CR1 の容量が小さいと、少し多めに乗っただけで AF41 が HTB で溢れ、
# 容量が落ちている間ずっと落ち続ける (2026-10-12 veth: 重み 2 で 3 本残り 0.71%)。
# そこで「溢れる確率」が閾値を超える容量では、AF41 の表 (table 41) だけ CR1 を外す。
# AF42 / AF43 は CR1 を使い続けるので、無線の容量は無駄にならない。
AF41_FLOWS = int(os.environ.get("RADWIN_AF41_FLOWS", "64"))        # iperf3 -P (lab_config_c2.sh)
FLOW_MBPS = float(os.environ.get("RADWIN_FLOW_MBPS", "125"))       # iperf3 -b 125000K


def af41_cap(mbps: float) -> float:
    """CR1 で AF41 が使える上限 [Mbps]。整形レートから AF42 / AF43 の保証 rate を引いた残り (C × 67/70)。"""
    return mbps * (1 - (WRR[1] + WRR[2]) / sum(WRR) / GUARANTEE_DIV)


def af41_overflow_risk(mbps: float, w: tuple[int, int, int]) -> float:
    """CR1 に乗る AF41 のフローが上限を超える確率。

    各フローが CR1 に乗る確率 q = w1 / (w1 + w2 + w3)、乗る本数 X は二項分布 B(AF41_FLOWS, q)。
    上限に収まる本数 k = floor(上限 / 1 本の速さ)。溢れる確率 = P(X > k)。
    """
    from math import comb
    if w[0] <= 0:
        return 0.0
    q = w[0] / sum(w)
    k = int(af41_cap(mbps) // FLOW_MBPS)
    if k >= AF41_FLOWS:
        return 0.0
    return max(0.0, 1 - sum(comb(AF41_FLOWS, i) * q ** i * (1 - q) ** (AF41_FLOWS - i) for i in range(k + 1)))


def _a41(w: int | None) -> dict:
    """AF41 の表の重みを渡す引数。判定しない条件 (None) では何も渡さない (P / P2 と同じ呼び出し)。"""
    return {} if w is None else {"af41_w1": w}


# ── 戻すのを待つ (条件 P4) ──────────────────────────────────────────
# 人が立つ・窓が濡れるなどで無線が数秒おきに途切れては戻ると、OSPF の隣接もそのたびに
# 消えては戻り、te_monitor は戻った瞬間に CR1 を経路へ戻していた。制御も MCS が一時的に
# 戻ると 6 秒で整形レートを上げ直していた。そのたびに無線の上へ AF41 を乗せ直し、次の
# 途切れでまた失っていた (2026-10-12 stand30@P)。--hold-down 秒を付けると、
#   - 制御: 最後に下げてから (または読めなくなってから) その秒数がたつまで上げない
#   - te_monitor: 重みファイルの HOLD= を読み、隣接が戻ってもその秒数安定するまで CR1 を戻さない


def af41_w1(mbps: float, w: tuple[int, int, int], limit: float | None) -> int | None:
    """AF41 の表の CR1 の重み。判定しない (limit が None) なら None (= 全クラス同じ重み)。"""
    if limit is None:
        return None
    return 0 if af41_overflow_risk(mbps, w) > limit else w[0]


def apply_route(mbps: int, label: str = "16005", af41_w1: int | None = None) -> tuple[tuple[int, int, int], bool]:
    return apply_weights(weights_for(mbps), label, af41_w1)


def apply_weights(w: tuple[int, int, int], label: str = "16005",
                  af41_w1: int | None = None) -> tuple[tuple[int, int, int], bool]:
    """経路表に重みを書く。重み 0 の経路は nexthop から外す (Linux は weight 0 を受け付けない)。
    af41_w1 を渡すと、table 41 (AF41) の CR1 だけその重みにする。"""
    ok = True
    for tbl in TABLES:
        cmd = ["ip", "netns", "exec", "LER_Ingress", "ip", "route", "replace",
               "table", str(tbl), "10.20.0.0/16"]
        ws = (af41_w1, *w[1:]) if tbl == 41 and af41_w1 is not None else w
        for (via, dev), wt in zip(NEXTHOPS, ws):
            if wt <= 0:
                continue
            cmd += ["nexthop", "encap", "mpls", label, "via", via,
                    "dev", dev, "weight", str(wt)]
        code, out = sh(cmd)
        if code != 0:
            ok = False
            print(f"  [NG] table {tbl} の経路更新に失敗: {out}")
    return w, ok


# ── P′ (改良版) の部品 ─────────────────────────────────────────────
TE_KICK_FILE = os.environ.get("RADWIN_TE_KICK_FILE", str(Path(TE_PID_FILE).parent / "te_monitor.kick"))


def notify_te_monitor() -> bool:
    """te_monitor が待っている FIFO に 1 行書き、重みファイルをすぐ読み直させる (待ち 最大 2 秒をなくす)。

    シグナルは使わない: bash 5.1 の read -t は、trap があってもシグナルで中断されない。
    FIFO の場所は te_monitor が te_monitor.kick に書いている。書けなくても制御は止めない。
    """
    try:
        fifo = Path(TE_KICK_FILE).read_text().strip()
        fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
        try:
            os.write(fd, b"KICK\n")
        finally:
            os.close(fd)
        return True
    except (OSError, ValueError):
        return False


def route_w1(table: int = 41) -> int | None:
    """経路表の CR1 (leri-cr1) の重み。CR1 が経路に無ければ 0、読めなければ None。"""
    code, out = sh(["ip", "netns", "exec", "LER_Ingress", "ip", "route", "show", "table", str(table)])
    if code != 0:
        return None
    m = re.search(r"dev leri-cr1(?: weight (\d+))?", out)
    return (int(m.group(1)) if m.group(1) else 1) if m else 0


def wait_routes(expect: dict[int, int], timeout: float = 2.0, step: float = 0.1) -> float | None:
    """経路表の CR1 の重みが {表: 重み} のとおりになるまで待つ。かかった秒数、時間切れなら None。"""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if all(route_w1(t) == w for t, w in expect.items()):
            return time.monotonic() - t0
        time.sleep(step)
    return None


def load_efficiency(path: str | None) -> dict[int, float]:
    """MCS ごとの効率の表 (JSON: {"9": 0.86, "12": 0.568, ...})。無ければ空 (= 全部 0.52)。"""
    if not path:
        return {}
    import json
    try:
        return {int(k): float(v) for k, v in json.loads(Path(path).read_text()).items()
                if not str(k).startswith("_")}
    except (OSError, ValueError) as e:
        print(f"  [WARN] 効率の表を読めません ({path}): {e} → 0.52 を使う")
        return {}


def chain_capacity(hops: list[dict], table: dict[int, float], default: float = 0.52) -> float:
    """2 区間それぞれの PHY × (その MCS の効率) の小さいほう [Mbps]。"""
    caps = [h["tx_phy_mbps"] * table.get(h.get("tx_mcs"), default) for h in hops if h.get("connected")]
    return min(caps) if caps else 0.0


def te_monitor_owns_routes() -> bool:
    """経路表を te_monitor に任せるべきか。"""
    if ROUTE_OWNER == "self":
        return False
    if ROUTE_OWNER == "te_monitor":
        return True
    # te_monitor が書く pidfile で判定する。プロセス名で探す方式は、エディタや
    # less でファイルを開いただけ、あるいはコマンド文字列に名前を含むシェルでも
    # 「稼働中」と誤判定し、経路を誰も書かなくなるため使わない。
    # pid の再利用に備え、その pid が本当に frr_te_monitor.sh を実行しているか
    # /proc/<pid>/cmdline の引数で確かめる。
    try:
        pid = int(Path(TE_PID_FILE).read_text().strip())
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except (OSError, ValueError):
        return False
    args = [a.decode(errors="replace") for a in argv if a]
    if not args or Path(args[0]).name not in ("bash", "sh"):
        return False
    script = next((a for a in args[1:] if not a.startswith("-")), "")
    return Path(script).name == "frr_te_monitor.sh"


_publish_warned = False


def publish_weights(w: tuple[int, int, int], mbps: int, af41_w1: int | None = None,
                    hold: int | None = None) -> None:
    """適用中の重みを te_monitor に公開する。

    毎ポーリングで書き直す (TS が生存信号を兼ねる)。te_monitor は TS が古ければ
    制御が止まったとみなして静的値に戻る。書きかけを読ませないよう差し替えで書く。
    書けなくても制御は止めない (te_monitor が居なければ実害はない)。
    """
    global _publish_warned
    try:
        path = Path(WEIGHTS_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name("." + path.name + ".tmp")
        tmp.write_text(f"TS={int(time.time())}\nW1={w[0]}\nW2={w[1]}\nW3={w[2]}\n"
                       f"CR1_BW_MBPS={mbps}\n"
                       + (f"W1_AF41={af41_w1}\n" if af41_w1 is not None else "")
                       + (f"HOLD={hold}\n" if hold else ""))
        os.replace(tmp, path)
    except OSError as e:
        if not _publish_warned:
            print(f"  [WARN] 重みファイルを書けません ({WEIGHTS_FILE}): {e}")
            _publish_warned = True


_handing_over = False


def _handover(*_) -> None:
    global _handing_over
    _handing_over = True
    print("後継の制御に引き継ぐため停止します (重みファイルは残す)")
    sys.exit(0)


def clear_weights() -> None:
    """停止時に消す。古い重みを te_monitor に使わせないため。"""
    try:
        Path(WEIGHTS_FILE).unlink(missing_ok=True)
    except OSError:
        pass


def preflight() -> bool:
    """制御ループが前提にしている状態が本当に整っているか確かめる。

    どれか欠けていても tc / ip route は静かに空回りし、
    「制御した」という嘘のログだけが残る。それを防ぐ。
    """
    ok = True
    print("=== 事前確認 ===")

    for ns, dev in HTB_DEVS:
        _, out = sh(["ip", "netns", "exec", ns, "tc", "qdisc", "show", "dev", dev])
        if "htb" in out:
            print(f"  [OK] {ns}/{dev} に HTB qdisc あり")
        else:
            ok = False
            print(f"  [NG] {ns}/{dev} に HTB qdisc がない "
                  f"→ frr_dscp_te.sh が未適用")

    _, out = sh(["ip", "netns", "exec", "LER_Ingress",
                 "ip", "route", "show", "table", "41"])
    n = out.count("nexthop")
    if n >= 3:
        print(f"  [OK] table 41 は {n} 本の nexthop (マルチパス)")
    else:
        ok = False
        print(f"  [NG] table 41 の nexthop が {n} 本しかない (3本必要) "
              f"→ ROUTE_MODE=wcmp で frr_dscp_te.sh を再適用すること")

    _, out = sh(["ip", "netns", "exec", "LER_Ingress", "sysctl", "-n",
                 "net.ipv4.fib_multipath_hash_policy"])
    if out.strip() == "1":
        print("  [OK] fib_multipath_hash_policy = 1 (L3+L4ハッシュ)")
    else:
        ok = False
        print(f"  [NG] fib_multipath_hash_policy = {out.strip() or '不明'} "
              f"→ 1 でないと全フローが同一経路に偏る")

    print()
    return ok


CSV_HEADER = ["time",
              "hop1_phy", "hop1_mcs", "hop1_dbm",
              "hop2_phy", "hop2_mcs", "hop2_dbm",
              "est_mbps", "target_mbps", "applied_mbps", "w1", "action"]


def _now() -> str:
    return time.strftime("%H:%M:%S")


class Controller:
    """制御の状態を持ち、1回の観測ごとに判断・適用・記録する。

    状態は3つ。観測のたびに step() がどれか1つを実行する。
      通常       : 容量の変化に追従する (下げは即座、上げは UP_CONFIRM 回連続で確認)
      無線断     : 未接続が DOWN_CONFIRM 回続いたら CR1 を外す (重み 0)
      復帰確認中 : 無線断のあと、UP_CONFIRM 回続けて接続を確認してから戻す
    te_monitor が動いているとき (manual / failure_reroute) は、OSPF 隣接の消失による
    検知もあわせて働く。制御の検知は「接続中だがデータが通らない」壊れ方を
    見分けられないため、OSPF 側を置き換えるものではない。
    normal では te_monitor が止まっているので、無線断を外すのは制御だけになる。
    """

    def __init__(self, args, label: str, writer):
        self.args = args
        self.label = label
        self.writer = writer
        self.current = args.initial      # 適用中の CR1_BW [Mbps]。None は未初期化
        self.up_streak = 0               # 上げの連続確認回数
        self.link_down = False           # CR1 を外している (重み 0 を公開中)
        self.down_streak = 0             # 連続した「未接続」の回数
        self.recover_streak = 0          # 無線断のあとの連続した「接続」の回数
        self.last_down = 0.0             # 最後に「上げる理由がない」読み取りだった時刻 (P4 の待ち)

    def _hold_left(self) -> float:
        """P4: 上げる・戻すまでに、あと何秒待つか (待たない条件では 0)。

        数え始めは、最後に下げた時刻ではなく「上げる理由がない読み取り (下げる・据え置き・読めない)」
        の最後。途切れ途切れの無線では、低い読み取りは据え置き (同じ低い値) になり、下げた時刻が
        更新されない。そのため 10 秒前に一度下げただけで、6 秒よい読み取りが続くと上げていた
        (2026-10-12 veth flaptest@P4)。これで「10 秒続けてよい読み取り」のときだけ上げる。"""
        hold = getattr(self.args, "hold_down", 0) or 0
        return max(0.0, hold - (time.time() - self.last_down))

    def _pub_kw(self, a1: int | None) -> dict:
        """重みファイルに足す行 (AF41 の重み・戻すのを待つ秒数)。どちらも無い条件では何も足さない。"""
        kw = _a41(a1)
        if getattr(self.args, "hold_down", 0):
            kw["hold"] = int(self.args.hold_down)
        return kw

    # ── 1回の観測 ────────────────────────────────────────────────────
    def step(self, d: dict) -> None:
        if getattr(self.args, "eff_table", None) and d.get("ok"):
            d = dict(d, chain_mbps=round(chain_capacity(d["hops"], self.args.eff_table), 1))
        hops = d["hops"]
        h1 = hops[0] if hops[0].get("connected") else {}
        h2 = hops[1] if len(hops) > 1 and hops[1].get("connected") else {}
        if not d["ok"]:
            row = self._on_unreachable()
        elif self.link_down:
            row = self._on_recovering(d["chain_mbps"])
        else:
            row = self._on_normal(d["chain_mbps"], h1, h2)
        self._write(h1, h2, *row)
        self._publish()

    # ── 状態ごとの判断 ─────────────────────────────────────────────
    def _on_unreachable(self) -> tuple:
        """無線の状態を読めない。DOWN_CONFIRM 回続いたら CR1 を外す。"""
        self.down_streak += 1
        self.last_down = time.time()
        self.recover_streak = 0
        if self.link_down:
            action = "link_down"
        elif self.down_streak < DOWN_CONFIRM:
            action = f"link_lost({self.down_streak}/{DOWN_CONFIRM})"
            print(f"\n[{_now()}] {action} 無線の状態を読めない (もう1回続けば CR1 を外す)")
        else:
            ok, owner = self._remove_cr1()
            action = "link_down" if ok else "link_down_FAIL"
            if ok:
                self.link_down = True
            print(f"\n[{_now()}] {action} 無線断を{DOWN_CONFIRM}回連続で確認 "
                  f"→ CR1 を経路から外す (重み 0:100:100, 経路={owner})")
        w1 = 0 if self.link_down else (weights_for(self.current)[0] if self.current else 0)
        return 0, 0, self.current or 0, w1, action

    def _on_recovering(self, est: float) -> tuple:
        """無線断のあと。UP_CONFIRM 回続けて接続したら CR1 を戻す。それまでは外したまま。"""
        self.down_streak = 0
        self.recover_streak += 1
        target = max(MIN_MBPS, int(est * SAFETY))
        action = f"link_up_wait({self.recover_streak}/{UP_CONFIRM})"
        if self.recover_streak >= UP_CONFIRM and self._hold_left() > 0:
            action = f"link_up_hold({self._hold_left():.0f}s)"
        elif self.recover_streak >= UP_CONFIRM:
            _, ok, owner = self._apply_capacity(target)
            action = "link_up" if ok else "link_up_FAIL"
            if ok:
                self.link_down = False
                self.current = target
                self.recover_streak = 0
            print(f"\n[{_now()}] {action} 無線の復帰を{UP_CONFIRM}回連続で確認 "
                  f"→ CR1_BW {target}M 重み {':'.join(map(str, weights_for(target)))} (経路={owner})")
        w1 = 0 if self.link_down else weights_for(self.current)[0]
        return est, target, self.current or 0, w1, action

    def _on_normal(self, est: float, h1: dict, h2: dict) -> tuple:
        """容量の変化に追従する。閾値内の変化は無視する (フラッピング防止)。"""
        self.down_streak = 0
        target = max(MIN_MBPS, int(est * SAFETY))
        action = "keep"
        if self.current is None:
            action = "init"
        elif target < self.current * (1 - self.args.threshold):
            action = "down"          # 低下は即座に反映
            self.up_streak = 0
            self.last_down = time.time()
        elif target > self.current * (1 + self.args.threshold):
            self.up_streak += 1
            if self.up_streak < UP_CONFIRM:
                action = f"up_wait({self.up_streak}/{UP_CONFIRM})"
            elif self._hold_left() > 0:
                action = f"up_hold({self._hold_left():.0f}s)"   # P4: 最後に下げてから待つ
            else:
                action = "up"
        else:
            self.up_streak = 0
            self.last_down = time.time()     # 据え置き: 上げる理由がない読み取り

        applied = self.current
        phy = f"PHY {h1.get('tx_phy_mbps', 0):.0f}/{h2.get('tx_phy_mbps', 0):.0f}"
        if action in ("init", "down", "up"):
            ww, ok, owner = self._apply_capacity(target)
            if ok:
                applied = self.current = target
            else:
                action += "_FAIL"    # current を進めない。次のポーリングで再試行される
            self.up_streak = 0
            print(f"[{_now()}] {action:5s} {phy} (MCS {h1.get('tx_mcs')}/{h2.get('tx_mcs')}) "
                  f"→ 推定 {est:.0f} Mbps → CR1_BW {target}M "
                  f"重み {ww[0]}:{ww[1]}:{ww[2]} (経路={owner})")
        else:
            print(f"[{_now()}] {action:5s} {phy} "
                  f"(MCS {h1.get('tx_mcs')}/{h2.get('tx_mcs')} "
                  f"{h1.get('signal_dbm')}/{h2.get('signal_dbm')}dBm) "
                  f"推定 {est:.0f} / 現在 {self.current}M   ", end="\r")
        return est, target, applied or 0, weights_for(applied)[0] if applied else 0, action

    # ── 適用 ────────────────────────────────────────────────────────
    def _apply_capacity(self, target: int) -> tuple[tuple[int, int, int], bool, str]:
        """HTB を target に張り替え、重みを決める。(重み, 成否, 経路を書いた主体) を返す。

        te_monitor が動いていれば経路表は te_monitor が書く (重みは _publish で渡る)。
        """
        if self.args.dry_run:
            return weights_for(target), True, "-"
        if getattr(self.args, "pprime", False) and self.current is not None:
            return self._apply_capacity_ordered(target)
        ok_h = apply_htb(target)
        if te_monitor_owns_routes():
            return weights_for(target), ok_h, "te_monitor"
        ww, ok_r = apply_route(target, self.label, **_a41(self._af41_w1(target)))
        return ww, ok_h and ok_r, "self"

    def _af41_w1(self, mbps: int) -> int | None:
        """P3: AF41 の表の CR1 の重み (外すなら 0)。判定しない条件では None。"""
        return af41_w1(mbps, weights_for(mbps), getattr(self.args, "af41_guard", None))

    def _apply_capacity_ordered(self, target: int) -> tuple[tuple[int, int, int], bool, str]:
        """P′: 下げるときは経路が先、上げるときは HTB が先。

        P は HTB を先に絞り、経路の重みは te_monitor が次に読んだとき (最大約 2 秒後) に変わる。
        その間、CR1 に振り分けられたままの AF41 が、絞った HTB で溢れていた (2026-10-05 18:16)。
        """
        ww = weights_for(target)
        a1 = self._af41_w1(target)
        owner = "te_monitor" if te_monitor_owns_routes() else "self"
        if a1 is not None and (a1 == 0) != (self._af41_w1(self.current) == 0):
            print(f"  [P3] AF41 の CR1 を{'外す' if a1 == 0 else '戻す'} "
                  f"(溢れる確率 {af41_overflow_risk(target, ww):.1%}、閾値 {self.args.af41_guard:.1%})")

        def route() -> bool:
            if owner == "self":
                return apply_route(target, self.label, **_a41(a1))[1]
            publish_weights(ww, target, **self._pub_kw(a1))
            notify_te_monitor()
            expect = {41: ww[0]} if a1 is None else {41: a1, 42: ww[0]}
            took = wait_routes(expect)
            print(f"  [P′] 経路の重み {ww[0]}{'' if a1 is None else f' (AF41 {a1})'} の反映 "
                  + (f"{took:.2f} 秒" if took is not None else "を確認できず (2 秒で打ち切り)"))
            return True                            # 反映の確認は記録用。確認できなくても HTB は進める

        if target < self.current:
            ok_r = route()
            ok_h = apply_htb(target)
        else:
            ok_h = apply_htb(target)
            ok_r = route()
        return ww, ok_h and ok_r, owner

    def _remove_cr1(self) -> tuple[bool, str]:
        """CR1 を経路から外す。(成否, 経路を書いた主体) を返す。"""
        if self.args.dry_run:
            return True, "-"
        if te_monitor_owns_routes():
            if getattr(self.args, "pprime", False):   # P′: 次の読み込みを待たずに知らせる
                publish_weights(LINK_DOWN_WEIGHTS, 0, **self._pub_kw(None))
                notify_te_monitor()
            return True, "te_monitor"          # _publish で重み 0 が伝わる
        _, ok = apply_weights(LINK_DOWN_WEIGHTS, self.label)
        return ok, "self"

    def _publish(self) -> None:
        """適用中の重みを毎回公開する。値が変わらなくても TS を進め、
        制御が生きていることを te_monitor に伝える (無線断中も継続)。"""
        if self.args.dry_run:
            return
        if self.link_down:
            publish_weights(LINK_DOWN_WEIGHTS, 0, **self._pub_kw(None))
        elif self.current is not None:
            publish_weights(weights_for(self.current), self.current, **self._pub_kw(self._af41_w1(self.current)))

    # ── 記録 ────────────────────────────────────────────────────────
    def _write(self, h1: dict, h2: dict, est, target, applied, w1, action) -> None:
        self.writer.writerow([time.time(),
                              h1.get("tx_phy_mbps", 0), h1.get("tx_mcs", 0), h1.get("signal_dbm", ""),
                              h2.get("tx_phy_mbps", 0), h2.get("tx_mcs", 0), h2.get("signal_dbm", ""),
                              est, target, applied, w1, action])


def parse_args(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="1回だけ評価して終了")
    ap.add_argument("--dry-run", action="store_true", help="変更せず判断だけ表示")
    ap.add_argument("--check", action="store_true", help="既存の前提確認だけ実行して終了 (SSH・設定変更・ログ作成なし)")
    ap.add_argument("--log-csv", default=LOG_CSV,
                    help=f"CSV追記先 (既定: {LOG_CSV})。親ディレクトリは事前に作成すること")
    ap.add_argument("--interval", type=float, default=INTERVAL)
    ap.add_argument("--threshold", type=float, default=THRESHOLD)
    ap.add_argument("--initial", type=int, default=None,
                    help="現在の CR1_BW [Mbps]。省略時は最初の観測値を採用")
    ap.add_argument("--pprime", action="store_true",
                    help="改良版 P′: 容量を下げるときは経路の重みを先に変えてから HTB を絞る")
    ap.add_argument("--efficiency-table", default=None,
                    help="MCS ごとの効率の表 (JSON)。容量 = 小さいほうの区間の PHY × その MCS の効率")
    ap.add_argument("--af41-guard", type=float, default=None, metavar="RISK",
                    help="P3: CR1 に乗る AF41 が溢れる確率がこれを超える容量では、AF41 だけ CR1 から外す "
                         "(例 0.05。MCS 8 以上 (整形 1081M〜) は 1.5%% 以下で外れず、MCS 3 以下で外れる)")
    ap.add_argument("--hold-down", type=float, default=0, metavar="SEC",
                    help="P4: 最後に下げてからこの秒数は上げない。te_monitor にも重みファイルで伝え、"
                         "OSPF の隣接が戻ってもこの秒数安定するまで CR1 を戻させない (例 10)")
    a = ap.parse_args(argv)
    a.eff_table = load_efficiency(a.efficiency_table)
    return a


def main() -> int:
    args = parse_args()
    if args.check:
        return 0 if preflight() else 1

    if not preflight():
        if not args.dry_run:
            print("!! 前提条件が未達のため中止した。"
                  "上の [NG] を解消してから再実行すること")
            return 1
        print("!! 前提条件が未達。dry-run なので続行するが、"
              "本番前に必ず解消すること\n")

    # frr_measure.sh は SIGTERM で止める。既定の SIGTERM は finally を通らずに
    # 終了し、重みファイルが残る。SystemExit に変えて後始末を確実に行う。
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    # SIGUSR2 は「すぐ後継の制御が起動する」停止 (観測の条件の切り替え)。重みファイルを
    # 残し、後継が書き直すまで te_monitor に今の重みを使わせる (消すと約 2 秒間、
    # 固定の重みに戻ってしまう。2026-10-12 veth で確認)。古くなれば te_monitor が捨てる。
    signal.signal(signal.SIGUSR2, _handover)

    label = get_label()
    print(f"MPLS ラベル: {label}")

    log = open(args.log_csv, "a", newline="")
    writer = csv.writer(log)
    if log.tell() == 0:
        writer.writerow(CSV_HEADER)
    ctl = Controller(args, label, writer)

    print(f"制御ループ開始 (間隔 {args.interval}s / 閾値 ±{args.threshold:.0%} / "
          f"上げは {UP_CONFIRM} 回連続確認){' [dry-run]' if args.dry_run else ''}")
    print(f"ログ: {args.log_csv}")
    print()

    try:
        while True:
            t0 = time.time()
            ctl.step(collect())
            log.flush()
            if args.once:
                break
            time.sleep(max(0.0, args.interval - (time.time() - t0)))
    except KeyboardInterrupt:
        print("\n停止しました")
    finally:
        log.close()
        if not args.dry_run and not _handing_over:
            clear_weights()
    return 0


if __name__ == "__main__":
    sys.exit(main())
