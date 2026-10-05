#!/usr/bin/env python3
"""雨の観測: 無線区間を数日間監視し、定時と容量低下時に3クラスの全負荷計測を行う。

使い方 (どれも 1 行):
    sudo python3 scripts/radwin_observe.py start      # 観測を始める (裏で動き続ける)
    sudo python3 scripts/radwin_observe.py fault --label stand30   # 障害の実験: すぐに全負荷計測を始め、
                                                      # 通信が始まったら「今、障害を起こす」と表示する
    sudo python3 scripts/radwin_observe.py status     # 状態を見る
    sudo python3 scripts/radwin_observe.py stop       # 止める (欠測の検査をして結果名を付け替える)

常時動かすもの (止まったら起動し直し、events.csv に残す):
    te_monitor        経路表を書く。OSPF 隣接の消失で CR1 を外す (R4)
    controller        無線の MCS から HTB と重みを決める (R3)
    odu_logger        4台の ODU の受信電力・MCS を約 5 秒ごとに記録 (R1)
    state_logger      経路表・HTB・軽い負荷を 10 秒ごと、OSPF/BFD を 60 秒ごとに記録 (R5/R7/R8)
    load_server / load_client
                      MCS を保つための軽い負荷 50 Mbps (CR1 → LER_Egress)。全負荷計測の間は止める
    weather_logger    気象庁アメダス (名古屋) などを 10 分ごとに記録 (W1)。radwin_weather.py
    nowcast_logger    実験場所の降水強度 (気象庁 高解像度降水ナウキャスト) を 5 分ごとに記録。radwin_nowcast.py
    ping_logger       無線区間 (CR1 → 10.0.2.2) の往復遅延と応答を 1 秒ごとに記録。radwin_ping_logger.py
全負荷計測の終了時には、その時点の気象を 02_fullload/<回>/weather.json と probes.csv に残す。
日本時間の 0・6・12・18 時に、直近 6 時間の途中経過の報告書を 01_report/reports/ に作る
(results/frr/tools/summarize_rain_observation.py --report 6。最新は 01_report/latest_report.md)。

全負荷計測 (radwin_experiment.sh probe。経路表・HTB には触らない) を行う時:
    periodic     15 分ごと (毎時 0・15・30・45 分)
    degraded     CR1 の整形レートが直近 6 時間の中央値の 90% 以下になった、または CR1 が外れた
    repeat       低下が続く間、10 分ごと (2 時間を超えたら 30 分ごと)
    recovered    低下から戻ったとき
    どの計測も、前の計測の開始から 5 分以上あける。

記録: results/frr/radwin/observation/YYYYMMDD_running_rainobs_NN/ (並べ方は radwin_obs_layout.py と README.md)
    01_report/    途中経過の報告書・集計表・図        02_fullload/  全負荷計測 (probes.csv と 1 回ごと)
    03_radio/     ODU と ping                         04_control/   制御・経路表・OSPF/BFD・te_monitor
    05_weather/   アメダスとナウキャスト              06_system/    events.csv・check.txt・status.json・画面出力
"""
from __future__ import annotations

import argparse
import csv
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import radwin_obs_layout as lay  # noqa: E402
LAB = SCRIPTS.parent
OBS_ROOT = LAB / "results" / "frr" / "radwin" / "observation"
RUN_DIR = Path(os.environ.get("RADWIN_OBSERVE_RUN", "/run/radwin"))
PID_FILE = RUN_DIR / "observe.pid"
DIR_FILE = RUN_DIR / "observe.dir"
FINAL_FILE = RUN_DIR / "observe.final"     # 止めたあとの最終的なフォルダ名 (stop が読む)
FAULT_REQ = RUN_DIR / "fault_request.json"  # fault コマンド → 観測: すぐに全負荷計測を始めてほしい
FAULT_ACK = RUN_DIR / "fault_ack.json"      # 観測 → fault コマンド: 始めた (計測の開始時刻)
LOCK_FILE = Path(os.environ.get("RADWIN_OBSERVE_LOCK", "/run/lock/radwin_observe.lock"))

TICK = 2.0                 # 監督のループの間隔 [s]
PROBE_SECONDS = 120        # 全負荷計測の長さ
PERIOD = 900.0             # 平常時の全負荷計測の間隔 [s]。毎時 0・15・30・45 分 (2026-10-02 に 1 時間から変更)
RESTART_HOLD = 30.0        # 起動から 30 秒以内に止まった部品は、30 秒待ってから起動し直す
MIN_FREE_GB = 5.0          # 空き容量がこれを下回ったら全負荷計測を止める (常時の記録は続ける)
LOAD_RATE = "50M"
REPORT_HOURS = 6           # 途中経過の報告書の間隔 [時間]。日本時間の 0 時を起点に区切る
JST_OFFSET = 9 * 3600
SUMMARIZE = LAB / "results" / "frr" / "tools" / "summarize_rain_observation.py"
LOAD_PORT = "5301"


# ── 全負荷計測の時間割 (実機に触れない。単体で検証できる) ────────────────
class Scheduler:
    """controller.csv の整形レートと重みから、全負荷計測を行うべき時を決める。"""

    def __init__(self, period=PERIOD, repeat=600.0, slow_repeat=1800.0, slow_after=7200.0,
                 min_gap=300.0, drop=0.9, window=6 * 3600.0):
        self.period, self.repeat, self.slow_repeat = period, repeat, slow_repeat
        self.slow_after, self.min_gap, self.drop, self.window = slow_after, min_gap, drop, window
        self.history: list[tuple[float, float]] = []   # (時刻, 整形レート) CR1 が経路にある間だけ
        self.degraded = False
        self.degraded_since = 0.0
        self.pending: str | None = "start"   # 観測の始めに 1 回、基準の計測をする
        self.last_probe = -1e18
        self.last_slot: int | None = None
        self.latest: tuple[float, float, int] | None = None

    def feed(self, t: float, applied: float, w1: int) -> None:
        """controller.csv の1行を取り込む。"""
        self.latest = (t, applied, w1)
        # 低下中は基準を動かさない。6 時間を超える雨のあいだに基準が低い値へ
        # 入れ替わると、まだ低下しているのに「戻った」と判定してしまうため。
        if self.degraded:
            return
        if w1 > 0 and applied > 0:
            self.history.append((t, applied))
        cut = t - self.window
        while self.history and self.history[0][0] < cut:
            self.history.pop(0)

    def baseline(self) -> float | None:
        """平常時の整形レート = 直近 6 時間の中央値。

        最大値にすると、制御が 2 秒だけ上げてすぐ戻した値 (MCS が一瞬 10 になった) が基準になり、
        普段の値が「90% 以下」と判定されて、低下していないのに追加の計測が続いた (2026-10-03 に発生)。
        """
        if not self.history:
            return None
        v = sorted(a for _, a in self.history)
        return v[len(v) // 2]

    def _is_degraded(self) -> bool:
        if self.latest is None:
            return False
        _, applied, w1 = self.latest
        if w1 == 0:
            return True
        base = self.baseline()
        return base is not None and applied <= base * self.drop

    def decide(self, now: float, busy: bool) -> str | None:
        """今、全負荷計測を始めるならその理由を返す。始めないなら None。"""
        if self.latest is None:              # 制御の記録がまだ無い (起動直後・制御停止中)
            return None
        deg = self._is_degraded()
        if deg and not self.degraded:
            self.degraded, self.degraded_since = True, now
            self.pending = "degraded"
        elif not deg and self.degraded:
            self.degraded = False
            self.pending = "recovered"
        slot = int(now // self.period)
        if self.last_slot is None:
            self.last_slot = slot               # 起動直後の区切りはまたがない
        elif slot != self.last_slot:
            self.last_slot = slot
            if self.pending is None and not self.degraded:
                self.pending = "periodic"
        if self.degraded and self.pending is None:
            gap = self.slow_repeat if now - self.degraded_since > self.slow_after else self.repeat
            if now - self.last_probe >= gap:
                self.pending = "repeat"
        if busy or self.pending is None or now - self.last_probe < self.min_gap:
            return None
        reason, self.pending = self.pending, None
        self.last_probe = now
        return reason


class ControllerTail:
    """controller.csv に追記された行だけを読む。制御が起動し直して見出しが入っても読み飛ばす。"""

    def __init__(self, path: Path):
        self.path, self.pos = path, 0

    def read(self) -> list[tuple[float, float, int]]:
        try:
            with self.path.open() as f:
                f.seek(self.pos)
                text = f.read()
        except OSError:
            return []
        end = text.rfind("\n")
        if end < 0:
            return []
        self.pos += len(text[:end + 1].encode())
        rows = []
        for line in text[:end].splitlines():
            parts = line.split(",")
            if len(parts) < 12 or parts[0] == "time":
                continue
            try:
                rows.append((float(parts[0]), float(parts[9] or 0), int(float(parts[10] or 0))))
            except ValueError:
                continue
        return rows


# ── 部品の起動と見張り ──────────────────────────────────────────────
class Child:
    def __init__(self, name: str, argv: list[str], log: Path, env: dict):
        self.name, self.argv, self.log, self.env = name, argv, log, env
        self.proc: subprocess.Popen | None = None
        self.started = 0.0
        self.restarts = 0
        self.paused = False
        self.hold_until = 0.0

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> None:
        out = self.log.open("a")
        self.proc = subprocess.Popen(self.argv, stdout=out, stderr=subprocess.STDOUT,
                                     env=self.env, start_new_session=True)
        out.close()
        self.started = time.monotonic()

    def stop(self, wait: float = 10.0) -> None:
        if not self.alive():
            return
        _killpg(self.proc, signal.SIGTERM)
        try:
            self.proc.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            _killpg(self.proc, signal.SIGKILL)
            self.proc.wait()


def _killpg(proc: subprocess.Popen, sig: int) -> None:
    try:
        os.killpg(proc.pid, sig)
    except ProcessLookupError:
        pass


class Observer:
    def __init__(self, obs: Path, env: dict):
        self.obs, self.env = obs, env
        self.stop_flag = False
        lay.make(obs)
        self.sysdir = obs / lay.SYSTEM
        self.loaddir = obs / lay.FULLLOAD
        self.events = self.sysdir / "events.csv"
        self.probes_csv = self.loaddir / "probes.csv"
        radio, control, weather = obs / lay.RADIO, obs / lay.CONTROL, obs / lay.WEATHER
        py = sys.executable
        log = self.sysdir / "children.log"
        self.children = {
            "te_monitor": Child("te_monitor", ["bash", str(SCRIPTS / "frr_te_monitor.sh"),
                                               str(control / "te_monitor.log")], log, env),
            "controller": Child("controller", [py, "-u", str(SCRIPTS / "radwin_wcmp_controller.py"),
                                               "--interval", "2", "--log-csv", str(control / "controller.csv")],
                                self.sysdir / "controller.log", env),
            "odu_logger": Child("odu_logger", [py, "-u", str(SCRIPTS / "radwin_odu_logger.py"),
                                               "--dir", str(radio), "--interval", "5"], log, env),
            "state_logger": Child("state_logger", [py, "-u", str(SCRIPTS / "radwin_state_logger.py"),
                                                   "--dir", str(control)], log, env),
            "load_server": Child("load_server", ["ip", "netns", "exec", "LER_Egress", "iperf3", "-s",
                                                 "-p", LOAD_PORT], log, env),
            "load_client": Child("load_client", ["ip", "netns", "exec", "CR1", "iperf3", "-c", "10.0.2.2",
                                                 "-p", LOAD_PORT, "-b", LOAD_RATE, "-t", "86400"], log, env),
            "weather_logger": Child("weather_logger", [py, "-u", str(SCRIPTS / "radwin_weather.py"),
                                                       "--dir", str(weather)], log, env),
            "nowcast_logger": Child("nowcast_logger", [py, "-u", str(SCRIPTS / "radwin_nowcast.py"),
                                                       "--dir", str(weather)], log, env),
            "ping_logger": Child("ping_logger", [py, "-u", str(SCRIPTS / "radwin_ping_logger.py"),
                                                 "--dir", str(radio)], log, env),
        }
        # 受信側 (iperf3 -s) の起動を待ってから送信側を始める (同時に起動すると接続に失敗する)
        self.children["load_client"].hold_until = time.monotonic() + 3
        self.sched = Scheduler()
        self.tail = ControllerTail(control / "controller.csv")
        self.probe: subprocess.Popen | None = None
        self.probe_info: dict = {}
        self.probe_count = 0
        self.report: subprocess.Popen | None = None
        self.report_slot = self._report_slot(time.time())   # 起動直後は作らない (次の区切りから)

    # 記録
    def event(self, kind: str, detail: str = "") -> None:
        new = not self.events.exists()
        with self.events.open("a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["time", "event", "detail"])
            w.writerow([f"{time.time():.3f}", kind, detail])

    def write_status(self) -> None:
        st = {
            "time": time.time(),
            "children": {n: {"alive": c.alive(), "paused": c.paused, "restarts": c.restarts}
                         for n, c in self.children.items()},
            "probe_running": self.probe is not None,
            "probe_count": self.probe_count,
            "degraded": self.sched.degraded,
            "baseline_mbps": self.sched.baseline(),
            "latest": self.sched.latest,
        }
        tmp = self.sysdir / "status.json.tmp"
        tmp.write_text(json.dumps(st, ensure_ascii=False))
        tmp.replace(self.sysdir / "status.json")

    # 見張り
    def supervise(self) -> None:
        now = time.monotonic()
        for c in self.children.values():
            if c.paused or c.alive() or now < c.hold_until:
                continue
            if c.proc is not None:                      # 起動済みのものが止まった
                code = c.proc.returncode
                c.restarts += 1
                quick = now - c.started < RESTART_HOLD
                self.event("child_exit", f"{c.name} code={code}"
                           + (f" (起動から{now - c.started:.0f}秒。{RESTART_HOLD:.0f}秒待って再起動)" if quick else ""))
                c.proc = None
                if quick:
                    c.hold_until = now + RESTART_HOLD
                    continue
            c.start()
            self.event("child_start", f"{c.name} pid={c.proc.pid}")

    # 全負荷計測
    def start_probe(self, reason: str) -> None:
        free = shutil.disk_usage(self.obs).free / 1e9
        if free < MIN_FREE_GB:
            self.event("probe_skip", f"{reason} 空き容量 {free:.1f} GB < {MIN_FREE_GB} GB")
            return
        load = self.children["load_client"]
        load.paused = True
        load.stop()
        load.proc = None                                 # 止めたのはこちら。再起動の回数に数えない
        self.event("load_pause", "全負荷計測のため軽い負荷を止める")
        time.sleep(3)                                   # 軽い負荷の残りが抜けるのを待つ
        env = dict(self.env, RADWIN_PROBE_ROOT=str(self.loaddir))
        log = (self.sysdir / "probes.log").open("a")
        log_pos = log.tell()
        self.probe = subprocess.Popen(
            ["bash", str(SCRIPTS / "radwin_experiment.sh"), "probe", str(PROBE_SECONDS), "rainobs"],
            stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        log.close()
        self.probe_info = {"start": time.time(), "reason": reason, "log_pos": log_pos}
        self.event("probe_start", reason)

    def poll_probe(self) -> None:
        if self.probe is None or self.probe.poll() is None:
            return
        code = self.probe.returncode
        folder = _probe_result_dir(self.sysdir / "probes.log", self.probe_info.get("log_pos", 0))
        result = "success" if folder and "_success_" in folder.name else "fail"
        end = time.time()
        wx = snapshot_weather(folder)
        new = not self.probes_csv.exists()
        with self.probes_csv.open("a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["start", "end", "reason", "exit_code", "result", "folder"] + PROBE_WEATHER)
            w.writerow([f"{self.probe_info['start']:.0f}", f"{end:.0f}",
                        self.probe_info["reason"], code, result, folder.name if folder else ""]
                       + [wx.get(k, "") for k in PROBE_WEATHER])
        self.event("probe_end", f"{self.probe_info['reason']} code={code} {result}")
        self.probe = None
        self.probe_count += 1
        load = self.children["load_client"]
        load.paused = False                              # 次の見張りで起動し直される
        self.event("load_resume", "")

    @staticmethod
    def _report_slot(t: float) -> int:
        return int((t + JST_OFFSET) // (REPORT_HOURS * 3600))

    def maybe_report(self, now: float) -> None:
        """日本時間の区切り (0・6・12・18 時) を越えたら、報告書を裏で作る。計測は止めない。"""
        if self.report is not None and self.report.poll() is not None:
            self.event("report_end", f"code={self.report.returncode}")
            self.report = None
        slot = self._report_slot(now)
        if slot == self.report_slot or self.report is not None:
            return
        self.report_slot = slot
        log = (self.sysdir / "report.log").open("a")
        self.report = subprocess.Popen([sys.executable, str(SUMMARIZE), "--dir", str(self.obs),
                                        "--report", str(REPORT_HOURS)],
                                       stdout=log, stderr=subprocess.STDOUT, env=self.env,
                                       start_new_session=True)
        log.close()
        self.event("report_start", f"直近 {REPORT_HOURS} 時間")

    def check_fault_request(self, now: float) -> None:
        """fault コマンドの依頼があれば、間隔の決まりを待たずに全負荷計測を始める。
        計測の最中なら、終わってから始める (依頼はそのまま残す)。"""
        if self.probe is not None or not FAULT_REQ.exists():
            return
        try:
            req = json.loads(FAULT_REQ.read_text())
        except (OSError, ValueError):
            FAULT_REQ.unlink(missing_ok=True)
            return
        FAULT_REQ.unlink(missing_ok=True)
        label = re.sub(r"[^A-Za-z0-9_.-]", "", str(req.get("label", "")))[:40] or "fault"
        self.start_probe(f"fault:{label}")
        self.sched.last_probe = now                      # このあとの定期の計測も 5 分あける
        FAULT_ACK.write_text(json.dumps({"id": req.get("id"), "start": self.probe_info.get("start"),
                                         "reason": f"fault:{label}"}))

    def run(self) -> int:
        self.event("observe_start", str(self.obs))
        last_check_day = time.strftime("%Y%m%d")
        while not self.stop_flag:
            self.supervise()
            for t, applied, w1 in self.tail.read():
                self.sched.feed(t, applied, w1)
            self.poll_probe()
            self.check_fault_request(time.time())
            reason = self.sched.decide(time.time(), busy=self.probe is not None)
            if reason:
                self.start_probe(reason)
            self.maybe_report(time.time())
            day = time.strftime("%Y%m%d")
            if day != last_check_day:                    # 日付が変わったら欠測の検査
                last_check_day = day
                run_check(self.obs)
            self.write_status()
            for _ in range(int(TICK / 0.5)):
                if self.stop_flag:
                    break
                time.sleep(0.5)
        return self.shutdown()

    def shutdown(self) -> int:
        self.event("observe_stop", "")
        if self.probe is not None and self.probe.poll() is None:
            # 途中で打ち切ると、その回が fail になり、コンテナ内の iperf3 も残る。終わるまで待つ
            self.event("probe_wait", "全負荷計測の終了を待つ")
            try:
                self.probe.wait(timeout=PROBE_SECONDS + 120)
            except subprocess.TimeoutExpired:
                _killpg(self.probe, signal.SIGTERM)
                try:
                    self.probe.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    _killpg(self.probe, signal.SIGKILL)
                self.event("probe_abort", self.probe_info.get("reason", ""))
            self.poll_probe()
        # 制御を先に止める (SIGTERM で重みファイルを消す)。経路表は te_monitor が最後に書いたまま残る
        order = ["load_client", "load_server", "controller", "odu_logger", "state_logger",
                 "weather_logger", "nowcast_logger", "ping_logger", "te_monitor"]
        for name in order + [n for n in self.children if n not in order]:
            if name in self.children:
                self.children[name].stop()
        self.write_status()
        return 0


# 全負荷計測の一覧 (probes.csv) に並べる気象の項目。全項目は各回の weather.json にある
PROBE_WEATHER = ["obs_time", "weather_name", "temp", "humidity", "dew_point",
                 "precipitation10m", "precipitation1h", "wind", "wind_dir_name",
                 "nc_valid_jst", "nc_mmh_lo", "nc_mmh_hi", "error"]


def snapshot_weather(folder: Path | None) -> dict:
    """計測の終了時点の気象を取り、計測フォルダに weather.json として残す。失敗しても計測は続ける。"""
    out = (folder or Path("/tmp")) / "weather.json"
    try:
        subprocess.run([sys.executable, str(SCRIPTS / "radwin_weather.py"), "--snapshot", str(out)],
                       timeout=60, capture_output=True)
        return json.loads(out.read_text())
    except (subprocess.TimeoutExpired, OSError, ValueError) as e:
        return {"error": f"snapshot: {e}"}


def _probe_result_dir(log: Path, pos: int) -> Path | None:
    """radwin_experiment.sh が最後に表示する「結果: <フォルダ> (終了コード …)」から、その回のフォルダを得る。"""
    try:
        with log.open("rb") as f:
            f.seek(pos)
            text = f.read().decode(errors="replace")
    except OSError:
        return None
    found = re.findall(r"^結果: (\S+) \(終了コード", text, re.M)
    return Path(found[-1]) if found else None


def run_check(obs: Path) -> None:
    subprocess.run([sys.executable, str(SCRIPTS / "radwin_observe_check.py"), str(obs)],
                   stdout=(lay.sub(obs, lay.SYSTEM) / "check.txt").open("w"), stderr=subprocess.STDOUT)


# ── 入口 ──────────────────────────────────────────────────────────
def lab_env(fake_dir: str | None) -> dict:
    """radwin_experiment.sh と同じ設定 (LAB_MODE=c2, lab_config_c2.sh) を環境変数に入れる。"""
    out = subprocess.run(["bash", "-c", "set -a; LAB_MODE=c2; ROUTE_MODE=wcmp; "
                          f"source '{SCRIPTS}/lab_config_c2.sh'; env -0"],
                         capture_output=True, check=True).stdout
    env = dict(kv.split("=", 1) for kv in out.decode().split("\0") if "=" in kv)
    env.pop("RADWIN_FAKE_ODU_DIR", None)
    if fake_dir:
        env["RADWIN_FAKE_ODU_DIR"] = fake_dir
    return env


def _cr1_lere_is_physical() -> bool:
    """実機 (c2) では cr1-lere は物理 NIC で、/sys/class/net/<名前>/device がある。veth には無い。"""
    r = subprocess.run(["ip", "netns", "exec", "CR1", "test", "-e", "/sys/class/net/cr1-lere/device"])
    return r.returncode == 0


_NAME = re.compile(r"^(\d{8})(?:-(\d{4}|\d{8}))?_(running|success|fail)_(.+)$")


def _strip_result(name: str) -> str:
    """'20261002-1003_success_rainobs_04' → '20261002_rainobs_04' (終わりの日と結果語を外す)。"""
    m = _NAME.match(name)
    return f"{m.group(1)}_{m.group(4)}" if m else name


def final_name(name: str, result: str, end: float) -> str:
    """止めたときの名前。日付をまたいだ観測は、始めた日のあとに終わった日を付ける。

    '20261002_running_rainobs_04' を 10/03 に止めた → '20261002-1003_success_rainobs_04'
    年をまたいだときは終わりの日を 8 桁で書く (例 20261231-20270101)。同じ日なら付けない。
    すでに付いている名前に使っても、終わりの日を付け直すだけ (何度使ってもよい)。
    """
    m = _NAME.match(name)
    if not m:
        return name.replace("_running_", f"_{result}_", 1)
    start, _, _, rest = m.groups()
    e = time.strftime("%Y%m%d", time.localtime(end))
    span = start if e == start else f"{start}-{e[4:] if e[:4] == start[:4] else e}"
    return f"{span}_{result}_{rest}"


def new_obs_dir(root: Path, purpose: str) -> Path:
    day = time.strftime("%Y%m%d")
    prefix = f"{day}_{purpose}"
    n = 0
    for d in (LAB / "results" / "frr").rglob(f"{day}_*"):
        base = _strip_result(d.name)
        m = re.match(rf"^{re.escape(prefix)}_(\d+)$", base)
        if d.is_dir() and m:
            n = max(n, int(m.group(1)))
    return root / f"{day}_running_{purpose}_{n + 1:02d}"


def _running_pid() -> int | None:
    try:
        pid = int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except PermissionError:          # sudo なしの status から root のプロセスを見たとき
        return pid
    except OSError:
        return None
    return pid


def cmd_start(a) -> int:
    if os.geteuid() != 0:
        sys.exit("sudo python3 scripts/radwin_observe.py start として実行してください")
    if _running_pid():
        sys.exit(f"[NG] すでに観測中です (status で確認)。フォルダ: {DIR_FILE.read_text().strip()}")
    if a.fake_odu_dir and os.environ.get("RADWIN_ALLOW_FAKE") != "1":
        sys.exit("[NG] --fake-odu-dir は veth での確認専用です。RADWIN_ALLOW_FAKE=1 を付けたときだけ使えます")
    for pat in ("frr_te_monitor.sh", "radwin_wcmp_controller.py"):
        if subprocess.run(["pgrep", "-f", pat], capture_output=True).returncode == 0:
            sys.exit(f"[NG] {pat} がすでに動いています。止めてから始めてください: sudo pkill -f {pat}")
    if subprocess.run(["pgrep", "-f", f"iperf3 .*-p {LOAD_PORT}"], capture_output=True).returncode == 0:
        sys.exit(f"[NG] {LOAD_PORT} 番の iperf3 (手動の負荷や radwin_live_monitor.py) が動いています。止めてから始めてください")
    if a.fake_odu_dir and _cr1_lere_is_physical():
        sys.exit("[NG] cr1-lere が物理 NIC です (実機の構成)。偽の ODU は veth でしか使えません")
    env = lab_env(a.fake_odu_dir)
    # 既知の状態から始める (経路 3 本・HTB・重み 6:25:25)。そのあと前提を確認する
    for step in (["prepare"], ["check"]):
        r = subprocess.run(["bash", str(SCRIPTS / "radwin_experiment.sh"), *step], env=env)
        if r.returncode != 0:
            sys.exit(f"[NG] radwin_experiment.sh {step[0]} が失敗しました。上の表示を確認してください")
    obs = Path(a.dir) if a.dir else new_obs_dir(a.root, a.purpose)
    obs.mkdir(parents=True)
    lay.make(obs)
    # 観測フォルダの親 (observation/) も root が作ると、ふだんのユーザーが README などを置けない
    uid_, gid_ = os.environ.get("SUDO_UID"), os.environ.get("SUDO_GID")
    if uid_ and gid_ and obs.parent.stat().st_uid == 0:
        os.chown(obs.parent, int(uid_), int(gid_))
    # 集計 (results/frr/tools/summarize_rain_observation.py) の出力先。観測中でも sudo なしで書けるようにする
    uid, gid = os.environ.get("SUDO_UID"), os.environ.get("SUDO_GID")
    if uid and gid:
        os.chown(obs / lay.REPORT, int(uid), int(gid))
    rev = subprocess.run(["git", "-C", str(LAB), "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    (obs / lay.SYSTEM / "run.info").write_text(
        f"started_at={time.strftime('%Y-%m-%dT%H:%M:%S%z')}\ngit={rev}\n"
        f"fake_odu_dir={a.fake_odu_dir or ''}\nprobe_seconds={PROBE_SECONDS}\nperiod={PERIOD:.0f}\nload={LOAD_RATE}\n")
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    log = (obs / lay.SYSTEM / "supervisor.log").open("a")
    proc = subprocess.Popen([sys.executable, "-u", __file__, "_daemon", str(obs)]
                            + (["--fake-odu-dir", a.fake_odu_dir] if a.fake_odu_dir else []),
                            stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
    PID_FILE.write_text(str(proc.pid))
    DIR_FILE.write_text(str(obs))
    time.sleep(5)
    if proc.poll() is not None:
        sys.exit(f"[NG] 観測がすぐに止まりました。{obs / lay.SYSTEM / 'supervisor.log'} を確認してください")
    print(f"観測を始めました: {obs}")
    print("状態: sudo python3 scripts/radwin_observe.py status")
    print("停止: sudo python3 scripts/radwin_observe.py stop")
    return 0


def cmd_daemon(a) -> int:
    obs = Path(a.obs)
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    # 既にあれば読み取りで開く。/run/lock は sticky で fs.protected_regular=2 のため、
    # 別ユーザーのファイルを O_CREAT で開くと root でも拒否される。
    try:
        lock = LOCK_FILE.open("r")
    except FileNotFoundError:
        lock = LOCK_FILE.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("[NG] 別の観測が動いています", flush=True)
        return 1
    ob = Observer(obs, dict(os.environ))
    signal.signal(signal.SIGTERM, lambda *_: setattr(ob, "stop_flag", True))
    signal.signal(signal.SIGINT, lambda *_: setattr(ob, "stop_flag", True))
    rc = 1
    try:
        rc = ob.run()
    finally:
        run_check(obs)
        result = "success" if rc == 0 else "fail"
        final = obs.with_name(final_name(obs.name, result, time.time()))
        uid, gid = os.environ.get("SUDO_UID"), os.environ.get("SUDO_GID")
        if uid and gid:
            subprocess.run(["chown", "-R", f"{uid}:{gid}", str(obs)])
        try:
            obs.rename(final)
            FINAL_FILE.write_text(str(final))
            print(f"結果: {final}", flush=True)
        except OSError as e:
            print(f"[WARN] 結果名への付け替えに失敗: {e}", flush=True)
        for p in (PID_FILE, DIR_FILE):
            p.unlink(missing_ok=True)
    return rc


def cmd_stop(a) -> int:
    if os.geteuid() != 0:
        sys.exit("sudo python3 scripts/radwin_observe.py stop として実行してください")
    pid = _running_pid()
    if not pid:
        print("観測は動いていません")
        return 0
    obs = DIR_FILE.read_text().strip() if DIR_FILE.exists() else ""
    FINAL_FILE.unlink(missing_ok=True)
    os.kill(pid, signal.SIGTERM)
    print("停止中 (全負荷計測の途中なら、その終了を待つので最大 4 分ほどかかります) ...")
    for _ in range(420):
        if _running_pid() is None:
            break
        time.sleep(1)
    else:
        print("[WARN] 7 分待っても止まりません。supervisor.log を確認してください")
        return 1
    if FINAL_FILE.exists():
        final = Path(FINAL_FILE.read_text().strip())
    else:                                                   # 2026-10-03 より前のプログラムで動いていた観測
        final = Path(obs.replace("_running_", "_success_", 1))
    named = final.with_name(final_name(final.name, "fail" if "_fail_" in final.name else "success", time.time()))
    if final.is_dir() and named != final:                   # 日付をまたいだのに終わりの日が付いていない
        final.rename(named)
        final = named
        print(f"フォルダ名に終わりの日を付けました: {final.name}")
    if final.is_dir() and not lay.is_new(final):           # 2026-10-03 より前の形で記録した観測は、ここで整理する
        lay.organize(final)
        uid, gid = os.environ.get("SUDO_UID"), os.environ.get("SUDO_GID")
        if uid and gid:
            subprocess.run(["chown", "-R", f"{uid}:{gid}", str(final)])
        print("記録をフォルダの役割ごとに整理しました (README.md を参照)")
    print(f"停止しました。検査結果: {lay.sub(final, lay.SYSTEM) / 'check.txt'}")
    return 0


def _wait(cond, timeout: float, step: float = 0.5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = cond()
        if v:
            return v
        time.sleep(step)
    return None


def cmd_fault(a) -> int:
    """障害の実験の 1 回 (または --count 回)。人が立つ・窓を濡らすなどの操作は、表示に合わせて人が行う。

    障害を起こした時刻を入力する必要はない。実際に電波が落ちた時刻は、集計スクリプトが
    受信電力・ping・制御の記録から割り出す (時刻はぴったりでなくてよい)。
    """
    if os.geteuid() != 0:
        sys.exit("sudo python3 scripts/radwin_observe.py fault ... として実行してください")
    if not _running_pid():
        sys.exit("[NG] 観測が動いていません。先に start してください")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", a.label):
        sys.exit("[NG] --label は英数字と _ . - だけ (例 stand30、wet1)")
    obs = Path(DIR_FILE.read_text().strip())
    loaddir = lay.sub(obs, lay.FULLLOAD)
    for i in range(a.count):
        rid = f"{time.time():.3f}"
        FAULT_ACK.unlink(missing_ok=True)
        FAULT_REQ.write_text(json.dumps({"id": rid, "label": a.label}))
        print(f"[{i + 1}/{a.count}] 全負荷計測を依頼しました ({a.label})。"
              "ほかの計測の最中なら、終わるまで待ちます (最大 3 分) ...", flush=True)
        ack = _wait(lambda: FAULT_ACK.exists() and json.loads(FAULT_ACK.read_text()).get("id") == rid
                    and json.loads(FAULT_ACK.read_text()), 240)
        if not ack:
            FAULT_REQ.unlink(missing_ok=True)
            sys.exit("[NG] 観測が依頼を受け取りませんでした。status で観測の状態を確かめてください")
        start = ack["start"]
        # 通信が実際に始まるのは、計測の準備 (約 20 秒) のあと。timebase.txt ができた時刻を合図にする
        tb = _wait(lambda: next((p for p in loaddir.glob("*_running_*/frr_observe/timebase.txt")
                                 if p.stat().st_mtime >= start - 1), None), 90)
        t0 = time.time()
        if tb is None:
            print("  (通信の開始を確認できませんでした。開始から約 20 秒後とみなします)")
        print(f"  {time.strftime('%H:%M:%S')} 通信が始まりました (120 秒間)。")
        print(f"  ▶ 今から約 20 秒後に障害を起こし ({a.label})、通信の終わり (約 100 秒後) までに元に戻してください。")
        print("    時刻はぴったりでなくてよい (実際の時刻は記録から割り出す)。", flush=True)
        for mark in (20, 60, 100):
            time.sleep(max(0.0, t0 + mark - time.time()))
            print(f"  {time.strftime('%H:%M:%S')} 通信開始から {mark} 秒"
                  + (" ← このあたりで障害を起こす" if mark == 20 else " ← これまでに元に戻す" if mark == 100 else ""),
                  flush=True)
        done = _wait(lambda: not json.loads((lay.sub(obs, lay.SYSTEM) / "status.json").read_text())
                     .get("probe_running"), 120, 1.0)
        rows = list(csv.DictReader((loaddir / "probes.csv").open())) if (loaddir / "probes.csv").exists() else []
        row = next((r for r in reversed(rows) if r["reason"] == ack["reason"]
                    and abs(float(r["start"]) - start) < 5), None)
        if done and row:
            loss = _af41_loss(lay.probe_dir(obs, row["folder"]) / "frr_observe" / "iperf3_af41.log")
            print(f"  {time.strftime('%H:%M:%S')} 計測が終わりました: {row['result']} / AF41 の損失率 {loss}")
            print(f"    結果: {row['folder']}")
        else:
            print("  (計測の終わりを確認できませんでした。probes.csv を確かめてください)")
        if i + 1 < a.count:
            wait = max(0.0, start + a.every - time.time())
            print(f"  次の回まで {wait:.0f} 秒待ちます ...", flush=True)
            time.sleep(wait)
    return 0


def _af41_loss(path: Path) -> str:
    try:
        m = re.findall(r"\[SUM\].*?\s(\d+)/(\d+) \([^)]*\)\s+receiver", path.read_text(errors="replace"))
        lost, total = map(int, m[-1])
        return f"{100 * lost / total:.4f}% ({lost} パケット)"
    except (OSError, IndexError, ValueError):
        return "不明"


def cmd_status(a) -> int:
    pid = _running_pid()
    if not pid:
        print("観測は動いていません")
        return 0
    obs = Path(DIR_FILE.read_text().strip())
    print(f"観測中 pid={pid}  フォルダ: {obs}")
    try:
        st = json.loads((lay.sub(obs, lay.SYSTEM) / "status.json").read_text())
    except (OSError, ValueError):
        print("  (status.json がまだありません)")
        return 0
    print(f"  最終更新: {time.time() - st['time']:.0f} 秒前")
    for n, c in st["children"].items():
        mark = "停止中(計測のため)" if c["paused"] else ("動作中" if c["alive"] else "止まっている")
        print(f"  {n:13s} {mark:12s} 再起動 {c['restarts']} 回")
    lat = st.get("latest")
    if lat:
        print(f"  CR1 の整形レート {lat[1]:.0f} Mbps / 重み {lat[2]} / 直近6時間の最大 {st.get('baseline_mbps') or 0:.0f} Mbps")
    print(f"  容量低下中: {'はい' if st['degraded'] else 'いいえ'} / 全負荷計測 {st['probe_count']} 回"
          + (" (実行中)" if st["probe_running"] else ""))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--purpose", default="rainobs", help="保存名の目的語")
    s.add_argument("--root", type=Path, default=OBS_ROOT)
    s.add_argument("--dir", default=None, help="保存先を直接指定 (確認用)")
    s.add_argument("--fake-odu-dir", default=None, help="veth 確認専用。偽の ODU の応答を置いたフォルダ")
    sub.add_parser("stop")
    sub.add_parser("status")
    fa = sub.add_parser("fault", help="障害の実験: すぐに全負荷計測を始め、障害を起こす合図を出す")
    fa.add_argument("--label", required=True, help="障害の種類 (英数字。例 stand5, stand30, wet1)")
    fa.add_argument("--count", type=int, default=1, help="続けて行う回数 (窓が乾くまで追うときなど)")
    fa.add_argument("--every", type=float, default=300, help="--count のときの間隔 [秒] (既定 5 分)")
    d = sub.add_parser("_daemon")
    d.add_argument("obs")
    d.add_argument("--fake-odu-dir", default=None)
    a = ap.parse_args()
    return {"start": cmd_start, "stop": cmd_stop, "status": cmd_status, "fault": cmd_fault,
            "_daemon": cmd_daemon}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
