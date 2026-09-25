#!/usr/bin/env python3
"""実機を操作しない回帰検証: python3 -m unittest discover -s scripts -p 'test_radwin_experiment.py' -v"""
from __future__ import annotations

import contextlib
import csv
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import radwin_wcmp_controller as controller


def sample(capacity):
    hop = {"connected": True, "tx_phy_mbps": 4620, "tx_mcs": 12, "signal_dbm": -30}
    return {"ok": capacity is not None, "chain_mbps": capacity or 0, "hops": [hop, hop]}


class ControllerTests(unittest.TestCase):
    def test_check_has_no_telemetry_mutation_or_csv(self):
        for valid in (True, False):
            with tempfile.TemporaryDirectory() as temp, contextlib.ExitStack() as stack:
                output = Path(temp) / "not-created.csv"
                stack.enter_context(patch.object(sys, "argv", ["controller", "--check", "--log-csv", str(output)]))
                stack.enter_context(patch.object(controller, "preflight", return_value=valid))
                collect = stack.enter_context(patch.object(controller, "collect"))
                shell = stack.enter_context(patch.object(controller, "sh"))
                self.assertEqual(controller.main(), 0 if valid else 1)
                collect.assert_not_called()
                shell.assert_not_called()
                self.assertFalse(output.exists())

    def replay(self, values, *, dry=False, failing=False, owner="self", published=None):
        with tempfile.TemporaryDirectory() as temp, contextlib.ExitStack() as stack:
            output = Path(temp) / "controller.csv"
            weights = Path(temp) / "radwin" / "weights.env"
            args = ["controller", "--log-csv", str(output)] + (["--dry-run"] if dry else [])
            stack.enter_context(patch.object(sys, "argv", args))
            # 実機の /run/radwin や pgrep に触れない
            stack.enter_context(patch.object(controller, "WEIGHTS_FILE", str(weights)))
            stack.enter_context(patch.object(controller, "ROUTE_OWNER", owner))
            stack.enter_context(patch.object(controller.signal, "signal"))
            if published is not None:
                real = controller.publish_weights
                def snap(w, mbps):
                    real(w, mbps)
                    published.append(weights.read_text())
                stack.enter_context(patch.object(controller, "publish_weights", side_effect=snap))
            stack.enter_context(patch.object(controller, "preflight", return_value=True))
            stack.enter_context(patch.object(controller, "get_label", return_value="16005"))
            stack.enter_context(patch.object(controller, "collect", side_effect=[*(sample(v) for v in values), KeyboardInterrupt()]))
            stack.enter_context(patch.object(controller.time, "sleep"))
            htb = stack.enter_context(patch.object(controller, "apply_htb", side_effect=[False, True] if failing else None, return_value=True))
            route = stack.enter_context(patch.object(controller, "apply_route", side_effect=lambda m, label: (controller.weights_for(m), True)))
            self.weights_calls = stack.enter_context(patch.object(controller, "apply_weights", side_effect=lambda w, label: (w, True))).call_args_list
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            self.assertEqual(controller.main(), 0)
            with output.open() as source:
                rows = list(csv.DictReader(source))
            # 停止時に重みファイルを消していること
            self.assertFalse(weights.exists(), "停止後も重みファイルが残っている")
            return rows, htb.call_args_list, route.call_args_list

    def test_drop_immediate_recovery_confirmed_three_times(self):
        rows, htb, route = self.replay([2400, 2400, 1200, 2400, 2400, 2400, None])
        # 最後の1回の未接続では外さない (link_lost)
        self.assertEqual([r["action"] for r in rows], ["init", "keep", "down", "up_wait(1/3)", "up_wait(2/3)", "up", "link_lost(1/2)"])
        self.assertEqual([c.args[0] for c in htb], [2160, 1080, 2160])
        self.assertEqual([c.args[0] for c in route], [2160, 1080, 2160])

    def test_failed_apply_is_retried_without_advancing_current(self):
        rows, htb, _ = self.replay([2400, 2400], failing=True)
        self.assertEqual([r["action"] for r in rows], ["init_FAIL", "init"])
        self.assertEqual([r["applied_mbps"] for r in rows], ["0", "2160"])
        self.assertEqual(len(htb), 2)

    def test_dry_run_records_without_applying(self):
        published = []
        rows, htb, route = self.replay([2400, 1200], dry=True, published=published)
        self.assertEqual([r["action"] for r in rows], ["init", "down"])
        self.assertEqual((htb, route), ([], []))
        self.assertEqual(published, [], "dry-run で te_monitor に重みを渡してはいけない")

    def test_weights_published_every_poll_as_heartbeat(self):
        published = []
        self.replay([2400, 2400, 1200, None], published=published)
        values = [dict(l.split("=") for l in p.split()) for p in published]
        # init / keep / down / link_down の4回すべてで公開 (TS が生存信号)
        self.assertEqual([v["W1"] for v in values], ["24", "24", "12", "12"])
        self.assertTrue(all(v["W2"] == v["W3"] == "100" for v in values))
        self.assertEqual([v["CR1_BW_MBPS"] for v in values], ["2160", "2160", "1080", "1080"])

    def test_te_monitor_owner_leaves_routes_alone(self):
        published = []
        rows, htb, route = self.replay([2400, 1200], owner="te_monitor", published=published)
        self.assertEqual([r["action"] for r in rows], ["init", "down"])
        self.assertEqual(route, [], "te_monitor 稼働中に経路表を書いてはいけない")
        self.assertEqual([c.args[0] for c in htb], [2160, 1080], "HTB は制御が書く")
        self.assertIn("W1=12", published[-1])

    def test_single_link_loss_does_not_remove_cr1(self):
        # 1回だけの読み取り失敗 (SSH の一時的なタイムアウトなど) で経路を外さない
        published = []
        rows, _, _ = self.replay([2400, None, 2400], owner="te_monitor", published=published)
        self.assertEqual([r["action"] for r in rows], ["init", "link_lost(1/2)", "keep"])
        self.assertEqual([p.split("W1=")[1].split()[0] for p in published], ["24", "24", "24"])

    def test_confirmed_link_down_publishes_zero_and_recovery_waits(self):
        published = []
        rows, htb, route = self.replay([2400, None, None, None, 2400, 2400, 2400, 2400],
                                       owner="te_monitor", published=published)
        self.assertEqual([r["action"] for r in rows],
                         ["init", "link_lost(1/2)", "link_down", "link_down",
                          "link_up_wait(1/3)", "link_up_wait(2/3)", "link_up", "keep"])
        # 断を確認してから復帰を3回確認するまで 0 を出し続ける
        w1 = [p.split("W1=")[1].split()[0] for p in published]
        self.assertEqual(w1, ["24", "24", "0", "0", "0", "0", "24", "24"])
        self.assertEqual([r["w1"] for r in rows], ["24", "24", "0", "0", "0", "0", "24", "24"])
        self.assertEqual(route, [], "te_monitor 稼働中は経路表に触れない")
        self.assertEqual(self.weights_calls, [])
        self.assertEqual([c.args[0] for c in htb], [2160, 2160], "復帰時に HTB を掛け直す")

    def test_self_owner_removes_cr1_from_route(self):
        rows, _, route = self.replay([2400, None, None, 2400, 2400, 2400], owner="self")
        self.assertEqual([c.args[0] for c in self.weights_calls], [(0, 100, 100)])
        self.assertEqual([c.args[0] for c in route], [2160, 2160], "init と復帰で書き直す")
        self.assertEqual(rows[-1]["action"], "link_up")

    def test_route_command_skips_zero_weight_nexthop(self):
        with patch.object(controller, "sh", return_value=(0, "")) as shell:
            controller.apply_weights((0, 100, 100), "16005")
        self.assertEqual(len(shell.call_args_list), 3)
        for call in shell.call_args_list:
            cmd = " ".join(call.args[0])
            self.assertNotIn("leri-cr1", cmd)
            self.assertIn("dev leri-cr2 weight 100", cmd)
            self.assertIn("dev leri-cr3 weight 100", cmd)


# frr_te_monitor.sh の _load_weights だけを取り出して検証する。
# スクリプト本体は docker を叩くので実行しない。
def _extract_load_weights():
    text = (SCRIPTS / "frr_te_monitor.sh").read_text()
    head = text.index("_load_weights() {")
    tail = text.index("\n}\n", head) + 3
    return text[head:tail]


class TeMonitorWeightTests(unittest.TestCase):
    def load(self, content, *, age_limit=10):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "weights.env"
            if content is not None:
                path.write_text(content)
            script = (
                'log(){ echo "LOG $*"; }\n'
                f'WEIGHTS_FILE="{path}"; WEIGHTS_MAX_AGE={age_limit}\n'
                'WCMP_W1=6; WCMP_W2=25; WCMP_W3=25\n'
                '_dw1=""; _dw2=""; _dw3=""; _dw_src=""\n'
                + _extract_load_weights() +
                '_load_weights\n_load_weights\n'   # 2回目はログを出さないこと
                'echo "RESULT ${_dw1}:${_dw2}:${_dw3} ${_dw_src}"\n')
            out = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                                 cwd=temp)
            self.assertEqual(out.returncode, 0, out.stderr)
            logs = [l for l in out.stdout.splitlines() if l.startswith("LOG")]
            result = out.stdout.splitlines()[-1].split()
            injected = (Path(temp) / "pwned").exists()
            return result[1], result[2], logs, injected

    def now(self):
        import time
        return int(time.time())

    def test_fresh_file_is_adopted(self):
        w, src, logs, _ = self.load(f"TS={self.now()}\nW1=13\nW2=100\nW3=100\nCR1_BW_MBPS=1171\n")
        self.assertEqual((w, src), ("13:100:100", "dynamic"))
        self.assertEqual(len(logs), 1, "同じ状態で2回呼んでもログは1回だけ")

    def test_missing_file_falls_back_to_static(self):
        self.assertEqual(self.load(None)[:2], ("6:25:25", "static"))

    def test_stale_file_falls_back_to_static(self):
        w, src, _, _ = self.load(f"TS={self.now() - 30}\nW1=13\nW2=100\nW3=100\n")
        self.assertEqual((w, src), ("6:25:25", "stale"))

    def test_malformed_or_out_of_range_is_rejected(self):
        for body in (f"TS={self.now()}\nW1=13\nW2=0\nW3=100\n",       # 有線の 0 は不可
                     f"TS={self.now()}\nW1=300\nW2=100\nW3=100\n",     # 255 超は不可
                     f"TS={self.now()}\nW1=13\nW2=100\n",              # 欠け
                     f"TS={self.now()}\nW1=abc\nW2=100\nW3=100\n"):    # 非数値
            self.assertEqual(self.load(body)[:2], ("6:25:25", "stale"), body)

    def test_zero_cr1_weight_is_accepted_as_link_down(self):
        w, src, _, _ = self.load(f"TS={self.now()}\nW1=0\nW2=100\nW3=100\n")
        self.assertEqual((w, src), ("0:100:100", "dynamic"))

    def routes(self, weights, state="0 0 0"):
        text = (SCRIPTS / "frr_te_monitor.sh").read_text()
        head = text.index("update_tables() {")
        body = text[head:text.index("\n}\n", head) + 3]
        script = ('log(){ echo "LOG $*"; }\nrefresh_labels(){ :; }\n'
                  'docker(){ echo "DOCKER $*"; }\n'
                  f'_load_weights(){{ _dw1={weights[0]}; _dw2={weights[1]}; _dw3={weights[2]}; }}\n'
                  f'ROUTE_MODE=wcmp; LERE_LABEL=16005; state=({state})\n'
                  + body + "update_tables\n")
        out = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout

    def test_update_tables_excludes_zero_weight_path(self):
        out = self.routes((0, 100, 100))
        route = next(l for l in out.splitlines() if l.startswith("DOCKER"))
        self.assertNotIn("leri-cr1", out.split("LOG")[0] + route)
        self.assertIn("dev leri-cr2 weight 100", out)
        self.assertIn("dev leri-cr3 weight 100", out)
        self.assertIn("CR1(w=0:除外)", out)

    def test_update_tables_keeps_positive_weight_path(self):
        out = self.routes((12, 100, 100))
        self.assertIn("dev leri-cr1 weight 12", out)

    def test_ospf_down_still_excludes_even_with_positive_weight(self):
        # OSPF が CR1 を落とした状態 (state=1) なら、制御の重みに関係なく外す
        out = self.routes((12, 100, 100), state="1 0 0")
        self.assertNotIn("leri-cr1", out)

    def test_leading_zero_is_decimal_not_octal(self):
        w, src, _, _ = self.load(f"TS={self.now()}\nW1=08\nW2=100\nW3=100\n")
        self.assertEqual((w, src), ("8:100:100", "dynamic"))

    def test_controller_output_is_readable_by_te_monitor(self):
        # 両者を別々に検証するだけでは形式の食い違いを見逃す。実物同士で通す。
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "radwin" / "weights.env"
            with patch.object(controller, "WEIGHTS_FILE", str(path)):
                controller.publish_weights(controller.weights_for(1171), 1171)
            w, src, _, _ = self.load(path.read_text())
        self.assertEqual((w, src), ("13:100:100", "dynamic"))

    def test_sigterm_removes_weights_file(self):
        # frr_measure.sh は SIGTERM で止める。finally が走らないと古い重みが残る。
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "weights.env"
            runner = Path(temp) / "run.py"
            runner.write_text(
                "import sys\n"
                f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
                "from unittest.mock import patch\n"
                "import radwin_wcmp_controller as c\n"
                "hop = {'connected': True, 'tx_phy_mbps': 4620, 'tx_mcs': 12, 'signal_dbm': -30}\n"
                "s = {'ok': True, 'chain_mbps': 2400, 'hops': [hop, hop]}\n"
                f"c.WEIGHTS_FILE = {str(path)!r}; c.ROUTE_OWNER = 'te_monitor'\n"
                f"sys.argv = ['c', '--log-csv', {str(Path(temp) / 'log.csv')!r}, '--interval', '0.05']\n"
                "with patch.object(c, 'preflight', return_value=True), \\\n"
                "     patch.object(c, 'get_label', return_value='16005'), \\\n"
                "     patch.object(c, 'collect', return_value=s), \\\n"
                "     patch.object(c, 'apply_htb', return_value=True):\n"
                "    c.main()\n")
            proc = subprocess.Popen([sys.executable, str(runner)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                import time
                deadline = time.time() + 10
                while not path.exists() and time.time() < deadline:
                    time.sleep(0.05)
                self.assertTrue(path.exists(), "制御が重みファイルを書かなかった")
                proc.send_signal(__import__("signal").SIGTERM)
                proc.wait(timeout=10)
            finally:
                if proc.poll() is None:
                    proc.kill()
            self.assertFalse(path.exists(), "SIGTERM 後も重みファイルが残っている")

    def test_file_contents_are_never_executed(self):
        _, src, _, injected = self.load(
            f"TS={self.now()}\nW1=$(touch pwned)\nW2=100\nW3=100\ntouch pwned\n")
        self.assertFalse(injected, "重みファイルの中身がシェルとして実行された")
        self.assertEqual(src, "stale")


# 偽コマンドは一時ディレクトリ内だけで使用。Docker/ip/pkill/SSHを実行しない。
FAKE_TOOL = r'''
import csv, json, os, signal, sys, time
from pathlib import Path
name = Path(sys.argv[0]).name
a = sys.argv[1:]
def event(kind):
    with open(os.environ['EVENTS'], 'a') as f:
        f.write(json.dumps({'kind': kind, 'pid': os.getpid(), 'args': a}) + '\n')
if name == 'id':
    print(0)
elif name == 'sleep':
    time.sleep(.015)
elif name == 'pkill':
    pass
elif name == 'ip':
    if '-n' in a and 'sysctl' in a: print(1)
elif name == 'python3':
    if any(x.endswith('radwin_wcmp_controller.py') for x in a):
        if '--check' in a:
            event('check')
        elif os.environ.get('SIM_CTRL_FAIL'):
            event('controller_failed')
            sys.exit(2)
        else:
            event('controller_start')
            target = a[a.index('--log-csv') + 1]
            with open(target, 'w') as f:
                f.write('time,action,applied_mbps\n1,init,2160\n')
            def stop(*unused):
                event('controller_stop')
                sys.exit(0)
            signal.signal(signal.SIGTERM, stop)
            while True: time.sleep(.02)
    elif any(x.endswith('plot_frr.py') for x in a):
        event('plot')
    else:
        os.execv(os.environ['REAL_PYTHON'], [os.environ['REAL_PYTHON'], *a])
elif name == 'docker':
    if a[0] == 'ps': print('LER_Ingress')
    elif a[0] == 'inspect': print(os.environ['NET_PID'])
    elif 'sysctl' in a and '-n' in a: print(1)
    elif 'iptables' in a: print('MARK')
    elif any(f'route {op}' in ' '.join(a) for op in ('add', 'replace')): event('route')
    elif 'route' in a and 'show' in a:
        print('encap mpls 16005 nexthop nexthop nexthop')
    elif os.environ.get('SIM_MEASURE_FAIL') and '-d' in a and 'Rx1' in a and 'iperf3' in a:
        time.sleep(.15)
        event('measurement_failure')
        sys.exit(1)
    elif 'iperf3' in a and '-c' in a:
        event('traffic')
        port = a[a.index('-p') + 1]
        if os.environ.get('SIM_IPERF_FAIL') and port == '2000':
            print('iperf3: error - simulated')
            sys.exit(1)
        for i in range(64): print(f'[{i}] connected to 10.20.1.1 port {port}')
        time.sleep(.3)
        print('[SUM] receiver')
    elif 'which' in a: print('/usr/bin/iperf3')
'''


# te_monitor の稼働判定 (pidfile) と、TERM で確実に終了することの検証。
def _extract_pidfile_block():
    text = (SCRIPTS / "frr_te_monitor.sh").read_text()
    head = text.index('TE_PID_FILE="${RADWIN_TE_PID_FILE')
    end = "trap 'exit 0' INT TERM\n"
    return text[head:text.index(end, head) + len(end)]


class TeMonitorOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temp, True)
        self.pidfile = self.temp / "run" / "te_monitor.pid"
        self.procs = []

    def tearDown(self):
        for proc in self.procs:
            proc.kill()
            proc.wait()

    def spawn(self, argv):
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
        self.procs.append(proc)
        time.sleep(0.2)
        return proc

    def owns(self, pid=None):
        if pid is not None:
            self.pidfile.parent.mkdir(parents=True, exist_ok=True)
            self.pidfile.write_text(f"{pid}\n")
        with patch.object(controller, "TE_PID_FILE", str(self.pidfile)), \
                patch.object(controller, "ROUTE_OWNER", "auto"):
            return controller.te_monitor_owns_routes()

    def monitor_script(self, body="while true; do sleep 0.1; done\n", *, with_block=False):
        script = self.temp / "frr_te_monitor.sh"
        head = ""
        if with_block:
            head = ('log(){ :; }\nMONITOR_FIFO=/nonexistent; MONITOR_PID=\n'
                    f'RADWIN_TE_PID_FILE="{self.pidfile}"\n' + _extract_pidfile_block())
        script.write_text(head + body)
        return script

    def test_no_pidfile_means_self(self):
        self.assertFalse(self.owns())

    def test_running_monitor_is_detected(self):
        proc = self.spawn(["bash", str(self.monitor_script())])
        self.assertTrue(self.owns(proc.pid))

    def test_dead_pid_is_ignored(self):
        proc = self.spawn(["bash", str(self.monitor_script())])
        proc.kill()
        proc.wait()
        self.assertFalse(self.owns(proc.pid))

    def test_reused_pid_by_viewer_is_ignored(self):
        # pid が再利用され、ファイルを開いているだけのプロセスに当たった場合
        proc = self.spawn(["tail", "-f", str(self.monitor_script())])
        self.assertFalse(self.owns(proc.pid))

    def test_garbage_pidfile_is_ignored(self):
        self.pidfile.parent.mkdir(parents=True)
        self.pidfile.write_text("not-a-pid")
        self.assertFalse(self.owns())

    def test_term_exits_and_removes_own_pidfile(self):
        # 以前は trap _cleanup INT TERM で、TERM 後もループが続いていた
        proc = self.spawn(["bash", str(self.monitor_script(with_block=True))])
        self.assertEqual(self.pidfile.read_text().strip(), str(proc.pid))
        self.assertTrue(self.owns())
        proc.terminate()
        self.assertEqual(proc.wait(timeout=3), 0)
        self.assertFalse(self.pidfile.exists())

    def test_exit_keeps_pidfile_of_newer_monitor(self):
        # 後から起動した te_monitor が pidfile を上書きした状態で終了する
        script = self.monitor_script(f'echo 999999 > "{self.pidfile}"\n', with_block=True)
        subprocess.run(["bash", str(script)], check=True, timeout=5)
        self.assertEqual(self.pidfile.read_text().strip(), "999999")


class SshTimeoutTests(unittest.TestCase):
    def test_hung_child_is_killed_at_timeout(self):
        # 無線断で ODU が消えると ssh が応答なしのまま残る。以前は終了を待ち続け、
        # 制御ループが 80 秒止まった。SIGHUP も無視する子で再現する。
        import radwin_ssh
        start = time.monotonic()
        code, _ = radwin_ssh._run_pty(["bash", "-c", "trap '' HUP; sleep 30"], "x", timeout=1.0)
        self.assertLess(time.monotonic() - start, 5.0, "時間切れで戻らない")
        self.assertNotEqual(code, 0)

    def test_normal_command_output_is_returned(self):
        import radwin_ssh
        code, out = radwin_ssh._run_pty(["bash", "-c", "echo hello"], "x", timeout=5.0)
        self.assertEqual((code, out), (0, "hello"))


def _extract_ospf_check():
    text = (SCRIPTS / "frr_te_monitor.sh").read_text()
    a = text.index('_nbr_in=""; _nbr_out=""')
    b = text.index("\n}\n", text.index("ospf_neighbor_full() {")) + 3
    c = text.index("_ospf_poll_last=0")
    d = text.index("\n}\n", text.index("check_ospf_neighbors() {")) + 3
    return text[a:b] + text[c:d]


NBR_HEADER = "Neighbor ID     Pri State           Up Time         Dead Time Address         Interface\n"


def nbr(*rids):
    return NBR_HEADER + "".join(f"{r}       1 Full/-          1h00m00s          2.5s 10.0.0.1  x:10.0.0.2\n" for r in rids)


class TeMonitorPathTests(unittest.TestCase):
    """te_monitor が入口側と出口側 (無線) の両方の隣接で経路の可否を決めること。"""

    def poll(self, ingress, egress, state="0 0 0", polls=1):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "in.txt").write_text(ingress)
            (Path(temp) / "out.txt").write_text(egress if egress is not None else "")
            fail_out = "1" if egress is None else "0"
            script = (
                'log(){ echo "LOG $*"; }\nupdate_tables(){ echo "UPDATE ${state[*]}"; }\n'
                f'docker(){{ if [[ "$*" == *frr-LER_Egress* ]]; then [ {fail_out} = 1 ] && return 1; cat {temp}/out.txt; '
                f'else cat {temp}/in.txt; fi; }}\n'
                'CR_ROUTER_IDS=("192.168.0.2" "192.168.0.3" "192.168.0.4"); CR_NAMES=(CR1 CR2 CR3)\n'
                f'state=({state})\n'
                + _extract_ospf_check()
                + "for n in $(seq %d); do _ospf_poll_last=0; check_ospf_neighbors; done\n" % polls
                + 'echo "STATE ${state[*]}"\n')
            out = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            lines = out.stdout.splitlines()
            return lines[-1].split(None, 1)[1], lines

    ALL = ("192.168.0.2", "192.168.0.3", "192.168.0.4")

    def test_wireless_side_loss_removes_cr1(self):
        state, lines = self.poll(nbr(*self.ALL), nbr("192.168.0.3", "192.168.0.4"))
        self.assertEqual(state, "1 0 0")
        self.assertTrue(any("出口側" in l and "CR1" in l for l in lines), lines)

    def test_ingress_side_loss_still_detected(self):
        state, lines = self.poll(nbr("192.168.0.3", "192.168.0.4"), nbr(*self.ALL))
        self.assertEqual(state, "1 0 0")
        self.assertTrue(any("入口側" in l for l in lines), lines)

    def test_unreadable_egress_falls_back_to_ingress_only(self):
        # 出口側を読めないことを「全隣接消失」と取り違えて全経路を外してはいけない
        state, lines = self.poll(nbr(*self.ALL), None, polls=2)
        self.assertEqual(state, "0 0 0")
        self.assertEqual(sum("[warn]" in l for l in lines), 1, "警告は1回だけ")

    def test_recovery_needs_both_sides(self):
        state, _ = self.poll(nbr(*self.ALL), nbr("192.168.0.3", "192.168.0.4"), state="1 0 0")
        self.assertEqual(state, "1 0 0", "出口側が戻るまで外したまま")
        state, lines = self.poll(nbr(*self.ALL), nbr(*self.ALL), state="1 0 0")
        self.assertEqual(state, "0 0 0")
        self.assertTrue(any(l.startswith("UPDATE") for l in lines))


class TimingConsistencyTests(unittest.TestCase):
    def test_weights_max_age_exceeds_worst_controller_cycle(self):
        # 無線断中は ODU 2台の SSH がともに時間切れになる。その1周より短い鮮度判定だと、
        # te_monitor が静的値へ戻り、外した CR1 を経路に戻してしまう。
        import re as _re
        import radwin_telemetry
        text = (SCRIPTS / "frr_te_monitor.sh").read_text()
        max_age = int(_re.search(r'RADWIN_WEIGHTS_MAX_AGE:-(\d+)', text).group(1))
        worst = len(radwin_telemetry.HOPS) * radwin_telemetry.SSH_TIMEOUT + controller.INTERVAL
        self.assertGreater(max_age, worst * 1.5)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        script_dir = self.root / "scripts"
        script_dir.mkdir()
        for name in ("radwin_experiment.sh", "frr_measure.sh", "lab_config.sh", "lab_config_c2.sh",
                     "radwin_wcmp_controller.py", "radwin_telemetry.py", "radwin_ssh.py",
                     "frr_te_monitor.sh", "run_all_scenarios.sh"):
            shutil.copyfile(SCRIPTS / name, script_dir / name)
        self.launcher = script_dir / "radwin_experiment.sh"
        # 本番のroot専用ロック位置をテストコピーの中だけ差し替える。
        self.launcher.write_text(self.launcher.read_text().replace("/run/lock/radwin_experiment.lock", str(self.root / "experiment.lock")))
        (script_dir / "frr_dscp_te.sh").write_text("#!/bin/bash\nprintf 'prepare\\n'\n")
        (self.root / "results/frr").mkdir(parents=True)
        (self.root / "results/frr/plot_frr.py").write_text("")
        self.fake_bin = self.root / "bin"
        self.fake_bin.mkdir()
        for name in ("docker", "ip", "pkill", "sleep", "id", "python3"):
            executable = self.fake_bin / name
            executable.write_text(f"#!{sys.executable}\n" + FAKE_TOOL)
            executable.chmod(0o755)
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(("CR", "TX", "WCMP_", "WRR_", "IPERF_", "SUDO_", "RADWIN_", "PFIFO_", "FRR_"))
                    and key not in ("PRIO_HI", "INGRESS_POLICE", "BASH_ENV", "SHELLOPTS")}
        self.env.update(PATH=f"{self.fake_bin}:{os.environ['PATH']}", REAL_PYTHON=sys.executable,
                        EVENTS=str(self.root / "events.jsonl"), NET_PID=str(os.getpid()))

    def run_cli(self, *args, **env):
        return subprocess.run(["bash", str(self.launcher), *args], cwd=self.root, env=self.env | env,
                              text=True, capture_output=True, timeout=20)

    def events(self):
        import json
        path = self.root / "events.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_plan_does_not_execute_or_create_results(self):
        result = self.run_cli("--plan", "run", "120", "20260919_preview_wcmp_01")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RADWIN_CONTROLLER_CSV=", result.stdout)
        self.assertIn("normal 20260919_running_preview_wcmp_01", result.stdout)
        self.assertEqual(self.events(), [])
        self.assertFalse(any((self.root / "results/frr").rglob("*preview*")))
        self.assertFalse((self.root / "experiment.lock").exists())

    def test_run_accepts_failure_reroute_but_not_failure(self):
        result = self.run_cli("--plan", "run", "60", "20260925_reroute_wcmp_01", "2", "failure_reroute")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RADWIN_CONTROLLER_CSV=", result.stdout)
        self.assertIn("60 failure_reroute 20260925_running_reroute_wcmp_01", result.stdout)
        # failure は迂回なしの比較用。動的制御と組み合わせない
        bad = self.run_cli("--plan", "run", "60", "20260925_nofail_wcmp_01", "2", "failure")
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("failure_reroute", bad.stdout + bad.stderr)
        # 障害シナリオは復旧 (t=40) を含む長さが必要
        self.assertNotEqual(self.run_cli("--plan", "run", "30", "x", "2", "failure_reroute").returncode, 0)
        self.assertEqual(self.events(), [])

    def test_manual_scenario_for_cable_pull(self):
        # 自動注入なし・te_monitor ありのシナリオ。run と measure の両方で使える
        result = self.run_cli("--plan", "run", "180", "20260925_unplug_wcmp_01", "2", "manual")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RADWIN_CONTROLLER_CSV=", result.stdout)
        self.assertIn("180 manual 20260925_running_unplug_wcmp_01", result.stdout)
        result = self.run_cli("--plan", "measure", "180", "manual", "20260925_unplugstatic_wcmp_01", "wcmp")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("RADWIN_CONTROLLER_CSV=", result.stdout)
        self.assertEqual(self.events(), [])

    def test_measure_script_has_manual_without_injection(self):
        text = (SCRIPTS / "frr_measure.sh").read_text()
        body = text[text.index("\nmanual)\n"):text.index("\nesac", text.index("\nmanual)\n"))]
        self.assertIn("frr_te_monitor.sh", body, "manual は te_monitor を起動する")
        self.assertNotIn("netem", body, "manual は自動で障害を注入しない")
        self.assertNotIn("hello-interval", body, "manual は OSPF タイマーを変えない")
        inject = text[text.index("# ── 障害注入プロセス"):text.index("# ── 計測開始")]
        self.assertNotIn("manual", inject, "注入ブロックの対象に manual を含めない")

    def test_static_plan_keeps_modes_and_scenarios(self):
        for scenario in ("normal", "failure", "failure_reroute", "all"):
            result = self.run_cli("--plan", "measure", "60", scenario, "20260919_static_ecmp_01", "ecmp")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("ROUTE_MODE=ecmp", result.stdout)
            self.assertNotIn("RADWIN_CONTROLLER_CSV=", result.stdout)
            self.assertIn("run_all_scenarios.sh" if scenario == "all" else f"60 {scenario} 20260919_running_static_ecmp_01", result.stdout)

    def test_tag_follows_naming_convention(self):
        """CLAUDE.md の YYYYMMDD_結果_目的_条件_連番 に沿うこと (実行中は running)。"""
        import re as _re
        # 未指定: 操作と条件から自動生成する
        out = self.run_cli("--plan", "run", "120").stdout
        m = _re.search(r"保存先: .*/radwin/dynamic/(\S+)", out)
        self.assertIsNotNone(m, out)
        self.assertRegex(m.group(1), r"^\d{8}_running_dynamic_wcmp_\d{2}$")

        # measure は comparison 側で、条件がタグに入る
        out = self.run_cli("--plan", "measure", "60", "normal", "", "ecmp").stdout
        m = _re.search(r"保存先: .*/radwin/comparison/(\S+)", out)
        self.assertIsNotNone(m, out)
        self.assertRegex(m.group(1), r"^\d{8}_running_compare_ecmp_\d{2}$")

        # 目的語だけ渡したら日付・条件・連番を補完する
        out = self.run_cli("--plan", "run", "120", "antenna").stdout
        m = _re.search(r"保存先: .*/radwin/dynamic/(\S+)", out)
        self.assertRegex(m.group(1), r"^\d{8}_running_antenna_wcmp_\d{2}$")

        # 完全形は結果語だけ付ける。結果語付きで渡されても付け直す
        out = self.run_cli("--plan", "run", "120", "20260919_antenna_wcmp_07").stdout
        self.assertIn("/radwin/dynamic/20260919_running_antenna_wcmp_07", out)
        out = self.run_cli("--plan", "run", "120", "20260919_success_antenna_wcmp_08").stdout
        self.assertIn("/radwin/dynamic/20260919_running_antenna_wcmp_08", out)

        # 連番は results/frr 全体を見て採番する (分類が違っても衝突しない)。
        # 日付は実行日で決まるため、テスト内でも同じ日付を使う。
        import datetime as _dt
        today = _dt.date.today().strftime("%Y%m%d")
        (self.root / f"results/frr/radwin/dynamic/{today}_seq_wcmp_01").mkdir(parents=True)
        (self.root / f"results/frr/radwin/comparison/{today}_seq_wcmp_04").mkdir(parents=True)
        # 結果語付きの新形式も同じ番号系列として数える
        (self.root / f"results/frr/radwin/dynamic/{today}_fail_seq_wcmp_06").mkdir(parents=True)
        out = self.run_cli("--plan", "run", "120", "seq").stdout
        self.assertIn(f"{today}_running_seq_wcmp_07", out)

    def test_rejects_overwrite_invalid_args_and_incompatible_control(self):
        (self.root / "results/frr/radwin/dynamic/20260919_existing_wcmp_01").mkdir(parents=True)
        (self.root / "results/frr/radwin/validation/20260919_oldtrial_wcmp_01").mkdir(parents=True)
        (self.root / "results/frr/radwin/dynamic/20260919_success_done_wcmp_01").mkdir(parents=True)
        cases = [("run", "120", "20260919_existing_wcmp_01"), ("run", "120", "../escape"),
                 ("run", "120", "20260919_oldtrial_wcmp_01"),
                 ("run", "120", "20260919_done_wcmp_01"),         # 結果語違いでも同じ実験番号
                 ("run", "120", "20260919_fail_done_wcmp_01"),
                 ("run", "0", "test"), ("run", "120", "test", "0"),
                 ("measure", "20", "failure"), ("prepare", "unknown")]
        for args in cases:
            self.assertNotEqual(self.run_cli("--plan", *args).returncode, 0, args)
        self.assertNotEqual(self.run_cli("--plan", "run", CR2_BW="8G").returncode, 0)
        self.assertEqual(self.events(), [])

    def test_dynamic_run_orders_routes_before_control_and_stops_child(self):
        result = self.run_cli("run", "2", "20260919_dynamic_wcmp_01")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.events()
        kinds = [e["kind"] for e in events]
        self.assertLess(max(i for i, k in enumerate(kinds) if k == "route"), kinds.index("controller_start"))
        self.assertLess(kinds.index("controller_start"), kinds.index("traffic"))
        self.assertLess(kinds.index("controller_stop"), kinds.index("plot"))
        pid = next(e["pid"] for e in events if e["kind"] == "controller_start")
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        result_dir = self.root / "results/frr/radwin/dynamic/20260919_success_dynamic_wcmp_01"
        self.assertIn("exit_code=0", (result_dir / "status.txt").read_text())
        self.assertIn("result=success", (result_dir / "status.txt").read_text())
        self.assertFalse((self.root / "results/frr/radwin/dynamic/20260919_running_dynamic_wcmp_01").exists())
        self.assertIn("controller: 1 samples", (result_dir / "validation.txt").read_text())
        self.assertIn("LAB_MODE=c2", (result_dir / "settings.env").read_text())

    def test_missing_traffic_is_not_reported_as_success(self):
        result = self.run_cli("run", "2", "20260919_missing_wcmp_01", SIM_IPERF_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        output = self.root / "results/frr/radwin/dynamic/20260919_fail_missing_wcmp_01"
        self.assertIn("AF42: 0/64 streams / NG", (output / "validation.txt").read_text())
        self.assertIn("exit_code=1", (output / "status.txt").read_text())

    def test_early_controller_exit_is_not_reported_as_success(self):
        result = self.run_cli("run", "2", "20260919_failed_wcmp_01", SIM_CTRL_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.root / "results/frr/radwin/dynamic/20260919_fail_failed_wcmp_01/controller.failed").exists())

    def test_static_measure_does_not_start_controller(self):
        result = self.run_cli("measure", "2", "normal", "20260919_static_wcmp_01", "wcmp")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("controller_start", [e["kind"] for e in self.events()])
        output = self.root / "results/frr/radwin/comparison/20260919_success_static_wcmp_01"
        self.assertTrue(output.is_dir())
        self.assertFalse((output / "controller.csv").exists())

    def test_measurement_error_also_stops_owned_controller(self):
        result = self.run_cli("run", "2", "20260919_aborted_wcmp_01", SIM_MEASURE_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        events = self.events()
        kinds = [e["kind"] for e in events]
        self.assertLess(kinds.index("measurement_failure"), kinds.index("controller_stop"))
        pid = next(e["pid"] for e in events if e["kind"] == "controller_start")
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        self.assertIn("exit_code=1", (self.root / "results/frr/radwin/dynamic/20260919_fail_aborted_wcmp_01/status.txt").read_text())


if __name__ == "__main__":
    unittest.main()
