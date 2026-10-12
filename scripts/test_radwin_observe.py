#!/usr/bin/env python3
"""雨の観測 (radwin_observe.py と記録係) の、実機を操作しない回帰検証。

    python3 -m unittest discover -s scripts -p 'test_radwin_observe.py' -v
"""
from __future__ import annotations

import csv
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from unittest.mock import patch  # noqa: E402

import radwin_observe as obs  # noqa: E402
import radwin_state_logger as st  # noqa: E402
import radwin_weather as wx  # noqa: E402
import radwin_nowcast as nc  # noqa: E402
import radwin_ping_logger as pl  # noqa: E402

H = 3600.0
DUMP = """Station c4:93:00:57:7c:72 (on wlan0)
	signal:  	-58 dBm
	tx bitrate:	2502.5 MBit/s MCS 9
	rx bitrate:	2502.5 MBit/s MCS 9
"""


class SchedulerTests(unittest.TestCase):
    def run_feed(self, s, t, applied, w1=13):
        s.feed(t, applied, w1)
        return s.decide(t, busy=False)

    def test_no_decision_without_controller_data(self):
        s = obs.Scheduler()
        self.assertIsNone(s.decide(10 * H, busy=False))

    def test_first_probe_at_start_then_every_quarter_hour(self):
        s = obs.Scheduler()
        t0 = 10 * H + 60                                       # 10:01
        self.assertEqual(self.run_feed(s, t0, 1171), "start")
        self.assertIsNone(self.run_feed(s, 10 * H + 600, 1171))
        self.assertEqual(self.run_feed(s, 10 * H + 902, 1171), "periodic")    # 10:15
        self.assertIsNone(self.run_feed(s, 10 * H + 1500, 1171))
        self.assertEqual(self.run_feed(s, 10 * H + 1801, 1171), "periodic")   # 10:30
        self.assertEqual(obs.PERIOD, 900.0)

    def test_drop_of_ten_percent_triggers_and_repeats_every_ten_minutes(self):
        s = obs.Scheduler()
        t0 = 10 * H + 60
        self.assertEqual(self.run_feed(s, t0, 1171), "start")
        # 5 分あける約束: 低下を検知しても、前の計測の開始から 5 分は待つ
        self.assertIsNone(self.run_feed(s, t0 + 100, 1000))
        self.assertEqual(self.run_feed(s, t0 + 300, 1000), "degraded")
        self.assertIsNone(self.run_feed(s, t0 + 600, 1000))
        self.assertEqual(self.run_feed(s, t0 + 900, 1000), "repeat")
        self.assertEqual(self.run_feed(s, t0 + 1500, 1000), "repeat")

    def test_small_change_is_not_degraded(self):
        s = obs.Scheduler()
        t0 = 10 * H + 60
        self.run_feed(s, t0, 1171)
        self.assertIsNone(self.run_feed(s, t0 + 400, 1060))   # 90.5% は低下とみなさない
        self.assertFalse(s.degraded)

    def test_brief_upward_blip_does_not_make_normal_look_degraded(self):
        # 2026-10-03 の実例: 制御が 2 秒だけ 1441M に上げてすぐ 1171M に戻した
        s = obs.Scheduler()
        t = 10 * H + 60
        self.run_feed(s, t, 1171)
        for _ in range(600):
            t += 2
            self.run_feed(s, t, 1171)
        self.run_feed(s, t + 2, 1441, w1=16)
        reasons = {self.run_feed(s, t + 4 + 2 * i, 1171) for i in range(300)}
        self.assertFalse(s.degraded)
        self.assertNotIn("degraded", reasons)
        self.assertEqual(s.baseline(), 1171)

    def test_link_down_weight_zero_is_degraded_even_with_same_rate(self):
        s = obs.Scheduler()
        t0 = 10 * H + 60
        self.run_feed(s, t0, 1171)
        self.assertEqual(self.run_feed(s, t0 + 400, 1171, w1=0), "degraded")

    def test_recovery_triggers_once_then_periodic_resumes(self):
        s = obs.Scheduler()
        t0 = 10 * H + 60
        self.run_feed(s, t0, 1171)
        self.assertEqual(self.run_feed(s, t0 + 400, 900), "degraded")
        self.assertEqual(self.run_feed(s, t0 + 800, 1171), "recovered")      # 10:14:20
        self.assertFalse(s.degraded)
        self.assertIsNone(self.run_feed(s, 10 * H + 905, 1171))   # 10:15 は回復時の計測から 5 分たっていない
        self.assertEqual(self.run_feed(s, 10 * H + 1160, 1171), "periodic")

    def test_long_degradation_slows_to_thirty_minutes(self):
        s = obs.Scheduler()
        t0 = 10 * H + 60
        self.run_feed(s, t0, 1171)
        self.run_feed(s, t0 + 400, 500)
        t = t0 + 400
        reasons = []
        while t < t0 + 400 + 4 * H:
            t += 60
            r = self.run_feed(s, t, 500)
            if r:
                reasons.append(t)
        early = [x for x in reasons if x - (t0 + 400) <= 2 * H]
        late = [x for x in reasons if x - (t0 + 400) > 2 * H + 1800]
        self.assertEqual(len(early), 12)
        self.assertGreaterEqual(len(late), 3)
        self.assertTrue(all(b - a == 600 for a, b in zip(early, early[1:])))
        self.assertTrue(all(b - a == 1800 for a, b in zip(late, late[1:])))

    def test_rain_longer_than_baseline_window_is_still_degraded(self):
        s = obs.Scheduler()
        t0 = 10 * H + 60
        self.run_feed(s, t0, 1171)
        self.run_feed(s, t0 + 400, 500)
        reasons = set()
        t = t0 + 400
        while t < t0 + 9 * H:                  # 基準の窓 (6 時間) を超えて低下が続く
            t += 60
            reasons.add(self.run_feed(s, t, 500))
        self.assertTrue(s.degraded)
        self.assertNotIn("recovered", reasons)
        self.assertNotIn("periodic", reasons)  # 低下中は定期の計測を重ねない
        self.assertEqual(s.baseline(), 1171)

    def test_busy_defers_but_keeps_pending(self):
        s = obs.Scheduler()
        s.feed(10 * H, 1171, 13)
        self.assertIsNone(s.decide(10 * H, busy=True))
        self.assertEqual(s.decide(10 * H + 2, busy=False), "start")


class ControllerTailTests(unittest.TestCase):
    def test_reads_only_complete_new_lines_and_skips_repeated_header(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "controller.csv"
            head = "time,hop1_phy,hop1_mcs,hop1_dbm,hop2_phy,hop2_mcs,hop2_dbm,est_mbps,target_mbps,applied_mbps,w1,action\n"
            p.write_text(head + "100.0,2502,9,-60,2502,9,-58,1301,1171,1171,13,init\n100.5,25")
            tail = obs.ControllerTail(p)
            self.assertEqual(tail.read(), [(100.0, 1171.0, 13)])
            with p.open("a") as f:      # 書きかけの行が完成し、制御の再起動で見出しが入る
                f.write("02,9,-60,2502,9,-58,1301,1171,1171,13,keep\n" + head
                        + "200.0,0,0,,0,0,,0,0,1171,0,link_down\n")
            self.assertEqual(tail.read(), [(100.5, 1171.0, 13), (200.0, 1171.0, 0)])
            self.assertEqual(tail.read(), [])


class StateParserTests(unittest.TestCase):
    def test_multipath_routes(self):
        text = ("10.20.0.0/16 proto static \n"
                "\tnexthop  encap mpls  16005 via 10.0.1.2 dev leri-cr1 weight 13 \n"
                "\tnexthop  encap mpls  16005 via 10.0.3.2 dev leri-cr2 weight 100 \n"
                "\tnexthop  encap mpls  16005 via 10.0.5.2 dev leri-cr3 weight 100 \n")
        self.assertEqual(st.parse_routes(text), "leri-cr1=13 leri-cr2=100 leri-cr3=100")

    def test_single_route_empty_table_and_failure(self):
        self.assertEqual(st.parse_routes("10.20.0.0/16 encap mpls 16005 via 10.0.3.2 dev leri-cr2 \n"),
                         "leri-cr2=1")
        self.assertEqual(st.parse_routes(""), "none")
        self.assertEqual(st.parse_routes(None), "")

    def test_htb_root_rate_both_spellings(self):
        for cid in ("1:0", "1:"):
            text = (f"class htb 1:1 parent {cid} prio 0 rate 117100Kbit ceil 1171Mbit burst 15Kb\n"
                    f"class htb {cid} root rate 1171Mbit ceil 1171Mbit burst 2927Kb cburst 2927Kb\n")
            self.assertEqual(st.parse_htb_root(text), "1171Mbit")
        self.assertEqual(st.parse_htb_root(None), "")

    def test_ospf_neighbors(self):
        text = ("\nNeighbor ID     Pri State           Up Time         Dead Time Address         Interface\n"
                "192.168.0.5       1 Full/-          21m15s             2.674s 10.0.2.2        cr1-lere:10.0.2.1\n"
                "192.168.0.1       1 Full/-          1w6d18h            2.672s 10.0.1.1        cr1-leri:10.0.1.2\n")
        self.assertEqual(st.parse_ospf(text), "192.168.0.5=Full 192.168.0.1=Full")
        self.assertEqual(st.parse_ospf("\nNeighbor ID     Pri State\n"), "none")

    def test_bfd_down_events_per_peer(self):
        text = ("BFD Peers:\n"
                "\tpeer 10.0.1.1 local-address 10.0.1.2 vrf default interface cr1-leri\n"
                "\t\tSession up events: 1\n\t\tSession down events: 0\n"
                "\tpeer 10.0.2.2 local-address 10.0.2.1 vrf default interface cr1-lere\n"
                "\t\tSession up events: 4\n\t\tSession down events: 3\n")
        self.assertEqual(st.parse_bfd_down(text, "10.0.2.2"), "3")
        self.assertEqual(st.parse_bfd_down(text, "10.0.1.1"), "0")
        self.assertEqual(st.parse_bfd_down(text, "10.0.9.9"), "")


class OduLoggerFakeTests(unittest.TestCase):
    def test_fake_odus_give_three_kinds_of_rows(self):
        with tempfile.TemporaryDirectory() as d:
            fake, out = Path(d) / "fake", Path(d) / "out"
            fake.mkdir()
            (fake / "192.168.1.31.txt").write_text(DUMP)
            (fake / "192.168.1.32.txt").write_text(DUMP)
            (fake / "192.168.1.33.txt").write_text("")          # 届くが相手がいない
            env = dict(os.environ, RADWIN_FAKE_ODU_DIR=str(fake))  # .34 はファイルなし = 届かない
            subprocess.run([sys.executable, str(SCRIPTS / "radwin_odu_logger.py"), "--dir", str(out),
                            "--rounds", "2", "--interval", "0.1"], env=env, check=True, timeout=30)
            files = list(out.glob("odu_*.csv"))
            self.assertEqual(len(files), 1)
            rows = list(csv.DictReader(files[0].open()))
            self.assertEqual(len(rows), 8)
            r = {x["odu"]: x for x in rows[:4]}
            self.assertEqual((r["192.168.1.31"]["connected"], r["192.168.1.31"]["signal_dbm"],
                              r["192.168.1.31"]["tx_mcs"]), ("1", "-58", "9"))
            self.assertEqual((r["192.168.1.33"]["connected"], r["192.168.1.33"]["why"]), ("0", "no_station"))
            self.assertEqual((r["192.168.1.34"]["connected"], r["192.168.1.34"]["why"]), ("0", "ssh_failed"))


class OduExtraTests(unittest.TestCase):
    # 2026-10-02 に .33 で実際に出た表示 (誤りの数は /sys から)
    REAL = """Station c4:93:00:60:35:e4 (on wlan0)
    inactive time:    0 ms
    rx bytes:    330464432089
    rx packets:    13030006
    tx bytes:    683458223
    tx packets:    44031813
    signal:      -55 dBm
    signal avg:    -54 dBm
    tx bitrate:    2502.5 MBit/s MCS 9
    rx bitrate:    2502.5 MBit/s MCS 9
    connected time:    14058 seconds
nd_tx_errors 0
nd_tx_dropped 0
nd_rx_errors 0
nd_rx_dropped 3
"""

    def test_real_dump_extra_fields(self):
        import radwin_odu_logger as ol
        vals = dict(zip([k for k, _ in ol.DUMP_EXTRA] + [f"nd_{k}" for k in ol.NETDEV], ol.parse_extra(self.REAL)))
        self.assertEqual((vals["signal_avg_dbm"], vals["connected_s"], vals["inactive_ms"]), ("-54", "14058", "0"))
        self.assertEqual((vals["dump_rx_bytes"], vals["dump_tx_packets"]), ("330464432089", "44031813"))
        self.assertEqual((vals["nd_tx_errors"], vals["nd_rx_dropped"]), ("0", "3"))
        self.assertEqual(len(ol.COLUMNS), 10 + len(ol.DUMP_EXTRA) + len(ol.NETDEV))

    def test_old_fake_dump_leaves_extra_blank(self):
        import radwin_odu_logger as ol
        self.assertEqual(set(ol.parse_extra(DUMP)), {""})


class CheckTests(unittest.TestCase):
    def write(self, path, header, rows):
        with path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)

    def test_gap_and_blank_column_are_ng(self):
        with tempfile.TemporaryDirectory() as d:
            o = Path(d)
            t0 = 1_790_000_000
            odu_rows = [[t0 + i * 5, ip, 1, "", -58, 9, 9, 2502.5, 2502.5, 1.0]
                        for i in range(20) for ip in ("192.168.1.31",)]
            odu_rows.append([t0 + 300, "192.168.1.31", 1, "", -58, 9, 9, 2502.5, 2502.5, 1.0])  # 205 秒の空白
            self.write(o / "odu_20260101.csv", ["time", "odu", "connected", "why", "signal_dbm", "tx_mcs",
                                                "rx_mcs", "tx_phy_mbps", "rx_phy_mbps", "read_s"], odu_rows)
            self.write(o / "state_20260101.csv", st.STATE_COLUMNS,
                       [[t0 + i * 10, "leri-cr1=13", "x", "x", "", "", 1] for i in range(10)])
            p = subprocess.run([sys.executable, str(SCRIPTS / "radwin_observe_check.py"), str(o)],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 1)
            self.assertIn("[NG] ODU 192.168.1.31 (R1)", p.stdout)
            self.assertIn("(205 秒)", p.stdout)
            self.assertIn("[NG] state.htb_leri_cr1: 空欄 10/10", p.stdout)


class SupervisorTests(unittest.TestCase):
    def make(self, d):
        o = obs.Observer(Path(d), dict(os.environ))
        return o

    def test_quick_exit_is_held_then_restarted_and_counted(self):
        with tempfile.TemporaryDirectory() as d:
            o = self.make(d)
            o.children = {"x": obs.Child("x", ["true"], Path(d) / "c.log", dict(os.environ))}
            o.supervise()                       # 初回起動
            o.children["x"].proc.wait()
            o.supervise()                       # すぐ止まった → 30 秒保留
            c = o.children["x"]
            self.assertEqual(c.restarts, 1)
            self.assertIsNone(c.proc)
            self.assertGreater(c.hold_until, time.monotonic())
            c.hold_until = 0
            o.supervise()
            self.assertIsNotNone(c.proc)
            ev = list(csv.DictReader((Path(d) / "06_system" / "events.csv").open()))
            self.assertEqual([e["event"] for e in ev], ["child_start", "child_exit", "child_start"])

    def test_paused_load_is_not_counted_as_exit(self):
        with tempfile.TemporaryDirectory() as d:
            o = self.make(d)
            o.children = {"load_client": obs.Child("load_client", ["sleep", "30"], Path(d) / "c.log",
                                                   dict(os.environ))}
            o.supervise()
            fake = Path(d) / "fake_experiment.sh"
            fake.write_text("echo \"結果: $RADWIN_PROBE_ROOT/20260101_success_rainobs_wcmp_01 (終了コード 0 / success)\"\n")
            orig = obs.SCRIPTS
            try:
                obs.SCRIPTS = Path(d)
                fake.rename(Path(d) / "radwin_experiment.sh")
                o_snap = patch.object(obs, "snapshot_weather", return_value={"weather_name": "雨", "temp": 18.2})
                o_snap.start()
                o.start_probe("periodic")
                self.assertIsNone(o.children["load_client"].proc)
                o.supervise()                   # 計測中は止めたまま
                self.assertIsNone(o.children["load_client"].proc)
                o.probe.wait()
                o.poll_probe()
            finally:
                obs.SCRIPTS = orig
                patch.stopall()
            o.supervise()                       # 計測後に再開
            c = o.children["load_client"]
            self.assertTrue(c.alive())
            self.assertEqual(c.restarts, 0)
            c.stop()
            pr = list(csv.DictReader((Path(d) / "02_fullload" / "probes.csv").open()))
            self.assertEqual((pr[0]["reason"], pr[0]["result"]), ("periodic", "success"))
            self.assertEqual(pr[0]["folder"], "20260101_success_rainobs_wcmp_01")
            self.assertEqual((pr[0]["weather_name"], pr[0]["temp"]), ("雨", "18.2"))


class ShutdownTests(unittest.TestCase):
    def test_stop_waits_for_running_probe_and_records_it(self):
        with tempfile.TemporaryDirectory() as d:
            o = obs.Observer(Path(d), dict(os.environ))
            o.children = {n: obs.Child(n, ["sleep", "30"], Path(d) / "c.log", dict(os.environ))
                          for n in ("load_client", "load_server", "controller", "odu_logger",
                                    "state_logger", "te_monitor")}
            script = Path(d) / "radwin_experiment.sh"
            script.write_text("sleep 2\necho \"結果: $RADWIN_PROBE_ROOT/20260101_success_rainobs_wcmp_01 (終了コード 0 / success)\"\n")
            orig = obs.SCRIPTS
            try:
                obs.SCRIPTS = Path(d)
                with patch.object(obs, "snapshot_weather", return_value={}):
                    o.start_probe("periodic")
                    o.shutdown()
            finally:
                obs.SCRIPTS = orig
            pr = list(csv.DictReader((Path(d) / "02_fullload" / "probes.csv").open()))
            self.assertEqual((pr[0]["result"], pr[0]["exit_code"]), ("success", "0"))
            ev = [e["event"] for e in csv.DictReader((Path(d) / "06_system" / "events.csv").open())]
            self.assertIn("probe_wait", ev)
            self.assertNotIn("probe_abort", ev)

    def test_load_client_waits_for_server_at_start(self):
        with tempfile.TemporaryDirectory() as d:
            o = obs.Observer(Path(d), dict(os.environ))
            self.assertGreater(o.children["load_client"].hold_until, time.monotonic())


class WeatherTests(unittest.TestCase):
    # 2026-10-02 20:30 に実際に取得したアメダス名古屋の値をもとにした応答
    POINT = {
        "20261002200000": {"temp": [21.3, 0], "humidity": [50, 0], "weather": [7, 0],
                           "precipitation10m": [0.5, 0], "wind": [4.0, 0], "windDirection": [14, 0]},
        "20261002203000": {"temp": [20.9, 0], "humidity": [51, 0], "precipitation10m": [0.0, 0],
                           "precipitation1h": [1.5, 0], "precipitation3h": [2.0, 0], "wind": [4.9, 0],
                           "gust": [13.6, 0], "gustTime": {"hour": 6, "minute": 46}, "windDirection": [15, 0],
                           "sun10m": [0, 0], "visibility": [20000.0, 1], "pressure": [1010.1, 0]},
    }

    def fake_get(self, url, timeout=20.0):
        import json
        if url.endswith("latest_time.txt"):
            return "2026-10-02T20:30:00+09:00"
        if "/point/51106/20261002_18" in url:
            return json.dumps(self.POINT)
        if "/point/51106/" in url:
            return "{}"
        if "open-meteo" in url:
            return json.dumps({"current": {"time": "2026-10-02T20:30", "weather_code": 61,
                                           "precipitation": 0.4, "cloud_cover": 100}})
        raise AssertionError(url)

    def test_latest_ten_minute_values_hourly_weather_and_flags(self):
        with patch.object(wx, "_get", side_effect=self.fake_get):
            r = wx.collect()
        self.assertEqual(r["obs_time"], "2026-10-02T20:30")
        self.assertEqual((r["temp"], r["humidity"], r["precipitation1h"]), (20.9, 51, 1.5))
        self.assertEqual((r["weather_time"], r["weather"], r["weather_name"]), ("2026-10-02T20:00", 7, "雨"))
        self.assertEqual(r["wind_dir_name"], "北北西")
        self.assertEqual(r["dew_point"], 10.4)
        self.assertEqual(r["flags"], "visibility=1")           # 正常 (0) 以外は記録する
        self.assertNotIn("gust", r)                            # その日の最大値なので取らない
        self.assertEqual((r["om_weather_code"], r["om_precipitation"]), (61, 0.4))
        self.assertEqual(r["error"], "")

    def test_network_failure_is_recorded_not_raised(self):
        with patch.object(wx, "_get", side_effect=OSError("network unreachable")):
            r = wx.collect()
        self.assertEqual(r["temp"], "")
        self.assertIn("amedas: network unreachable", r["error"])
        self.assertIn("open-meteo: network unreachable", r["error"])

    def test_dew_point_magnus(self):
        self.assertAlmostEqual(wx.dew_point(20.0, 100.0), 20.0, places=6)
        self.assertAlmostEqual(wx.dew_point(25.0, 50.0), 13.9, places=1)


class PingTests(unittest.TestCase):
    def test_real_ping_line_formats(self):
        # 2026-10-02 に ping -D -O で実際に出た形
        self.assertEqual(pl.parse_line("[1790943275.375323] 64 bytes from 10.0.2.2: icmp_seq=1 ttl=64 time=0.534 ms"),
                         ["1790943275.375323", "1", "0.534", "ok"])
        self.assertEqual(pl.parse_line("[1790943278.444432] no answer yet for icmp_seq=1"),
                         ["1790943278.444432", "1", "", "no_answer"])
        self.assertEqual(pl.parse_line("[1790943302.1] From 10.0.2.1 icmp_seq=7 Destination Host Unreachable")[3],
                         "unreachable")
        self.assertIsNone(pl.parse_line("PING 10.0.2.2 (10.0.2.2) 56(84) bytes of data."))


class NowcastTests(unittest.TestCase):
    def test_site_pixel_matches_fetched_tile(self):
        # 2026-10-02 に実際に取得した昭和区役所のタイルの位置
        self.assertEqual(nc.tile_pixel(35.1504, 136.9336), (901, 405, 128, 20))

    def test_palette_and_transparent(self):
        self.assertEqual(nc.classify((255, 255, 255, 0)), (0, 0))
        self.assertEqual(nc.classify((0, 65, 255, 255)), (10, 20))
        self.assertEqual(nc.classify((180, 0, 104, 255)), (80, None))
        self.assertIsNone(nc.classify((1, 2, 3, 255)))

    def fake_get(self, image):
        import io, json
        def get(url, timeout=20.0):
            if url.endswith("targetTimes_N1.json"):
                return json.dumps([{"basetime": "20261002121000", "validtime": "20261002121000"}]).encode()
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            return buf.getvalue()
        return get

    def test_collect_reads_site_and_neighbourhood(self):
        from PIL import Image
        im = Image.new("RGBA", (256, 256), (255, 255, 255, 0))
        im.putpixel((128, 20), (160, 210, 255, 255))     # 実験場所: 1〜5 mm/h
        im.putpixel((130, 22), (250, 245, 0, 255))       # 2 画素先: 20〜30 mm/h
        im.putpixel((140, 20), (180, 0, 104, 255))       # 5×5 の外は数えない
        with patch.object(nc, "_get", side_effect=self.fake_get(im)):
            r = nc.collect(35.1504, 136.9336)
        self.assertEqual((r["valid_jst"], r["mmh_lo"], r["mmh_hi"], r["area_max_hi"]),
                         ("2026-10-02T21:10", 1, 5, 30))
        self.assertEqual(r["error"], "")

    def test_unknown_colour_is_kept_not_guessed(self):
        from PIL import Image
        im = Image.new("RGBA", (256, 256), (12, 34, 56, 255))
        with patch.object(nc, "_get", side_effect=self.fake_get(im)):
            r = nc.collect(35.1504, 136.9336)
        self.assertEqual((r["mmh_lo"], r["rgba"]), ("unknown", "12-34-56-255"))


class ReportScheduleTests(unittest.TestCase):
    def test_report_slots_are_0_6_12_18_jst(self):
        import datetime as dt
        jst = dt.timezone(dt.timedelta(hours=9))
        at = lambda h, m: dt.datetime(2026, 10, 3, h, m, tzinfo=jst).timestamp()
        slot = obs.Observer._report_slot
        self.assertEqual(slot(at(5, 59)), slot(at(0, 0)))
        self.assertNotEqual(slot(at(6, 0)), slot(at(5, 59)))
        self.assertEqual(slot(at(6, 0)), slot(at(11, 59)))
        self.assertNotEqual(slot(at(18, 0)), slot(at(17, 59)))

    def test_report_runs_once_per_slot_in_background(self):
        with tempfile.TemporaryDirectory() as d:
            o = obs.Observer(Path(d), dict(os.environ))
            calls = []
            with patch.object(obs.subprocess, "Popen", side_effect=lambda *a, **k: calls.append(a[0]) or
                              type("P", (), {"poll": lambda self: None})()):
                o.maybe_report(time.time())                       # 起動直後の区切りでは作らない
                self.assertEqual(calls, [])
                o.report_slot -= 1                                 # 次の区切りを越えたことにする
                o.maybe_report(time.time())
                o.maybe_report(time.time())                        # 同じ区切りでは 1 回だけ
            self.assertEqual(len(calls), 1)
            self.assertIn("--report", calls[0])


class FaultTests(unittest.TestCase):
    def test_fault_request_starts_probe_immediately_and_acks(self):
        with tempfile.TemporaryDirectory() as d:
            o = obs.Observer(Path(d), dict(os.environ))
            req, ack = Path(d) / "req.json", Path(d) / "ack.json"
            started = []
            with patch.object(obs, "FAULT_REQ", req), patch.object(obs, "FAULT_ACK", ack), \
                 patch.object(o, "start_probe", side_effect=lambda r: (started.append(r),
                              setattr(o, "probe_info", {"start": 123.0, "reason": r}))):
                req.write_text('{"id": "x1", "label": "stand30; rm -rf /"}')
                o.probe = object()                      # 計測の最中は待つ (依頼は残す)
                o.check_fault_request(1000.0)
                self.assertEqual(started, [])
                self.assertTrue(req.exists())
                o.probe = None
                o.check_fault_request(1000.0)
            self.assertEqual(started, ["fault:stand30rm-rf@P"])   # 記号は落とす。条件の既定は P
            self.assertFalse(req.exists())
            import json
            self.assertEqual(json.loads(ack.read_text())["id"], "x1")
            self.assertEqual(o.sched.last_probe, 1000.0)          # このあとの定期の計測も 5 分あける


class ConditionTests(unittest.TestCase):
    def make(self, d):
        env = dict(os.environ, CR1_BW="2160M", WCMP_W1="6", WCMP_W2="25", WCMP_W3="25")
        o = obs.Observer(Path(d), env)
        o.children = {n: obs.Child(n, ["sleep", "30"], Path(d) / "c.log", env)
                      for n in ("controller", "te_monitor", "odu_logger", "load_client")}
        o.supervise()
        return o

    def run_cond(self, cond):
        with tempfile.TemporaryDirectory() as d:
            o = self.make(d)
            calls = []
            with patch.object(obs.time, "sleep"), \
                 patch.object(o, "_apply_static", side_effect=lambda routes: calls.append(routes) or 0):
                o.enter_condition(cond)
                stopped = {n: c.paused and c.proc is None for n, c in o.children.items()}
                o.leave_condition()
                o.supervise()                            # 止めた部品を起動し直す
                alive = {n: c.alive() for n, c in o.children.items()}
                restarts = {n: c.restarts for n, c in o.children.items()}
                for c in o.children.values():
                    c.stop()
            ev = [e["event"] for e in csv.DictReader((Path(d) / "06_system" / "events.csv").open())]
            return stopped, calls, alive, restarts, ev, o

    def test_S_stops_controller_only_and_fixes_htb(self):
        stopped, calls, alive, restarts, ev, o = self.run_cond("S")
        self.assertEqual({n for n, v in stopped.items() if v}, {"controller"})
        self.assertEqual(calls, [False])                 # 経路表は te_monitor が固定の重みへ書き直す
        self.assertTrue(all(alive.values()))
        self.assertEqual(set(restarts.values()), {0})    # 止めたのはこちら。再起動に数えない
        self.assertIn("condition_enter", ev)
        self.assertIn("condition_leave", ev)
        self.assertEqual(o.condition, "P")

    def test_N_also_stops_te_monitor_and_fixes_routes(self):
        stopped, calls, alive, restarts, ev, _ = self.run_cond("N")
        self.assertEqual({n for n, v in stopped.items() if v}, {"controller", "te_monitor"})
        self.assertEqual(calls, [True])
        self.assertTrue(all(alive.values()))

    def test_static_values_come_from_lab_config(self):
        with tempfile.TemporaryDirectory() as d:
            o = self.make(d)
            self.assertEqual(o._static(), (2160, (6, 25, 25)))
            for c in o.children.values():
                c.stop()

    def test_fault_request_with_condition_records_reason(self):
        with tempfile.TemporaryDirectory() as d:
            o = obs.Observer(Path(d), dict(os.environ))
            req, ack = Path(d) / "req.json", Path(d) / "ack.json"
            seen = []
            with patch.object(obs, "FAULT_REQ", req), patch.object(obs, "FAULT_ACK", ack), \
                 patch.object(o, "enter_condition", side_effect=lambda c: seen.append(("enter", c))), \
                 patch.object(o, "start_probe", side_effect=lambda r: (seen.append(("probe", r)),
                              setattr(o, "probe_info", {"start": 1.0, "reason": r}))):
                req.write_text('{"id": "a", "label": "stand30", "condition": "N"}')
                o.check_fault_request(10.0)
            self.assertEqual(seen, [("enter", "N"), ("probe", "fault:stand30@N")])


class EventDetectionTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(SCRIPTS.parent / "results" / "frr" / "tools"))
        import summarize_rain_observation as sm
        self.sm = sm

    def odu(self, t, ip, dbm, conn="1"):
        return {"time": str(t), "odu": ip, "signal_dbm": str(dbm), "connected": conn}

    def series(self, values):
        """values: {ip: [(秒, dBm または None=未接続), ...]}。計測の前 5 分は平常値。"""
        rows = []
        base = {"192.168.1.31": -60, "192.168.1.32": -59, "192.168.1.33": -56, "192.168.1.34": -57}
        for ip, b in base.items():
            for t in range(700, 1000, 5):
                rows.append(self.odu(t, ip, b))
            for t, v in values.get(ip, [(t, b) for t in range(1000, 1120, 5)]):
                rows.append(self.odu(t, ip, b if v == "base" else (0 if v is None else v), "0" if v is None else "1"))
        return rows

    def test_blockage_of_both_ends_is_detected_with_controller_delay(self):
        # 2026-10-05 18:16 の実例の形: 無線2 の両端が 1 回の読み取りで同時に下がる
        hop2 = lambda dip: [(t, dip if t == 1040 else "base") for t in range(1000, 1120, 5)]
        odu = self.series({"192.168.1.33": hop2(-67), "192.168.1.34": hop2(-64)})
        ctl = [{"time": "1042", "action": "down"}]
        r = self.sm.detect_event(odu, ctl, [], 1000, 1120)
        self.assertEqual((r["event"], r["event_hop"], r["event_len_s"], r["event_drop_db"]), (1, "無線2", 5, 11))
        self.assertEqual((r["ctl_first"], r["ctl_delay_s"]), ("down", 2.0))

    def test_one_sided_switching_of_32_is_not_an_event(self):
        # .32 だけが 7 dB 上下する現象は、遮られたのではない
        odu = self.series({"192.168.1.32": [(t, -52 if t % 20 else -66) for t in range(1000, 1120, 5)]})
        self.assertEqual(self.sm.detect_event(odu, [], [], 1000, 1120)["event"], 0)

    def test_disconnection_counts_as_event(self):
        odu = self.series({"192.168.1.34": [(t, None if 1050 <= t <= 1080 else "base") for t in range(1000, 1120, 5)]})
        r = self.sm.detect_event(odu, [], [], 1000, 1120)
        self.assertEqual((r["event"], r["event_drop_db"], r["event_len_s"]), (1, "切断", 35))


class NamingTests(unittest.TestCase):
    def at(self, y, m, d, h=12):
        import datetime as dt
        return dt.datetime(y, m, d, h, tzinfo=dt.timezone(dt.timedelta(hours=9))).timestamp()

    def test_same_day_keeps_single_date(self):
        self.assertEqual(obs.final_name("20261003_running_rainobs_01", "success", self.at(2026, 10, 3, 23)),
                         "20261003_success_rainobs_01")

    def test_crossing_days_appends_end_date(self):
        self.assertEqual(obs.final_name("20261002_running_rainobs_04", "success", self.at(2026, 10, 3)),
                         "20261002-1003_success_rainobs_04")
        self.assertEqual(obs.final_name("20261002_running_rainobs_04", "fail", self.at(2026, 10, 5)),
                         "20261002-1005_fail_rainobs_04")

    def test_crossing_year_uses_full_end_date(self):
        self.assertEqual(obs.final_name("20261231_running_rainobs_01", "success", self.at(2027, 1, 1)),
                         "20261231-20270101_success_rainobs_01")

    def test_reapplying_is_safe(self):
        name = "20261002-1003_success_rainobs_04"
        self.assertEqual(obs.final_name(name, "success", self.at(2026, 10, 3)), name)
        self.assertEqual(obs.final_name("20261003_success_rainobs_02", "success", self.at(2026, 10, 6)),
                         "20261003-1006_success_rainobs_02")

    def test_strip_and_lookup_without_end_date(self):
        sys.path.insert(0, str(SCRIPTS.parent / "results" / "frr" / "tools"))
        import result_paths
        for f in (obs._strip_result, result_paths.strip_result):
            self.assertEqual(f("20261002-1003_success_rainobs_04"), "20261002_rainobs_04")
            self.assertEqual(f("20261231-20270101_fail_rainobs_01"), "20261231_rainobs_01")
            self.assertEqual(f("20260925_success_unplug_wcmp_01"), "20260925_unplug_wcmp_01")


class LayoutTests(unittest.TestCase):
    OLD = ["odu_20261002.csv", "ping_20261002.csv", "controller.csv", "state_20261002.csv",
           "ospf_bfd_20261002.csv", "te_monitor.log", "weather_20261002.csv", "nowcast_20261002.csv",
           "probes.csv", "events.csv", "check.txt", "status.json", "run.info", "children.log",
           "probes.log", "judgement.txt"]

    def test_new_observation_has_numbered_folders_and_readme(self):
        import radwin_obs_layout as lay
        with tempfile.TemporaryDirectory() as d:
            obs.Observer(Path(d), dict(os.environ))
            names = sorted(p.name for p in Path(d).iterdir())
            self.assertEqual(names, ["01_report", "02_fullload", "03_radio", "04_control",
                                     "05_weather", "06_system", "README.md"])
            self.assertTrue(lay.is_new(Path(d)))

    def test_organize_moves_old_flat_folder_and_keeps_every_file(self):
        import radwin_obs_layout as lay
        with tempfile.TemporaryDirectory() as d:
            o = Path(d)
            for n in self.OLD:
                (o / n).write_text(n)
            (o / "summary" / "reports").mkdir(parents=True)
            (o / "summary" / "latest_report.md").write_text("r")
            (o / "probes" / "20261002_success_rainobs_wcmp_19" / "frr_observe").mkdir(parents=True)
            before = sorted(p.read_text() for p in o.rglob("*") if p.is_file())
            lay.organize(o)
            lay.organize(o)                                   # 2 回目は何もしない
            after = sorted(p.read_text() for p in o.rglob("*") if p.is_file() and p.name != "README.md")
            self.assertEqual(before, after)                   # 消えたファイルも増えたファイルもない
            self.assertTrue((o / "03_radio" / "odu_20261002.csv").exists())
            self.assertTrue((o / "04_control" / "controller.csv").exists())
            self.assertTrue((o / "05_weather" / "nowcast_20261002.csv").exists())
            self.assertTrue((o / "02_fullload" / "probes.csv").exists())
            self.assertTrue((o / "02_fullload" / "20261002_success_rainobs_wcmp_19" / "frr_observe").is_dir())
            self.assertTrue((o / "01_report" / "latest_report.md").exists())
            self.assertTrue((o / "01_report" / "judgement.txt").exists())
            self.assertTrue((o / "06_system" / "events.csv").exists())
            self.assertEqual(sorted(p.name for p in o.iterdir() if p.is_file()), ["README.md"])
            self.assertEqual([p.name for p in lay.find(o, "odu_*.csv")], ["odu_20261002.csv"])

    def test_find_reads_old_flat_layout_too(self):
        import radwin_obs_layout as lay
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "odu_20261002.csv").write_text("x")
            self.assertEqual(len(lay.find(Path(d), "odu_*.csv")), 1)
            self.assertEqual(lay.sub(Path(d), lay.REPORT), Path(d) / "summary")


class HarnessTests(unittest.TestCase):
    def test_probe_plan_uses_observe_and_never_reapplies_settings(self):
        p = subprocess.run(["bash", str(SCRIPTS / "radwin_experiment.sh"), "--plan", "probe", "120", "rainobs"],
                           capture_output=True, text=True, env=dict(os.environ, RADWIN_PROBE_ROOT="/tmp/probe_root"))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("frr_measure.sh 120 observe", p.stdout)
        self.assertNotIn("frr_dscp_te.sh", p.stdout)
        self.assertIn("/tmp/probe_root/", p.stdout)

    def test_measure_observe_keeps_te_monitor_routes_and_qdisc(self):
        text = (SCRIPTS / "frr_measure.sh").read_text()
        self.assertIn('if [ "$SCENARIO" != "observe" ]; then\n    pkill -f "frr_te_monitor.sh"', text)
        self.assertIn('[ "$SCENARIO" = "observe" ] || pkill -9 -f "frr_te_monitor.sh"', text)
        block = text.split("\nobserve)\n", 1)[1].split(";;", 1)[0]
        for forbidden in ("ip route", "tc ", "vtysh", "frr_te_monitor.sh /tmp"):
            self.assertNotIn(forbidden, block)

    def test_other_actions_are_refused_during_observation(self):
        text = (SCRIPTS / "radwin_experiment.sh").read_text()
        self.assertIn('exec 8</run/lock/radwin_observe.lock', text)
        self.assertNotIn('exec 8>/run/lock/radwin_observe.lock', text)


if __name__ == "__main__":
    unittest.main()


class PPrimeTests(unittest.TestCase):
    """改良版 P′ (radwin_wcmp_controller.py --pprime --efficiency-table)。"""

    def setUp(self):
        import radwin_wcmp_controller as ctl
        self.ctl = ctl

    def make(self, current=1171):
        args = self.ctl.parse_args(["--pprime"])
        c = self.ctl.Controller(args, "16005", csv.writer(open(os.devnull, "w")))
        c.current = current
        return c

    def run_apply(self, target, owner="te_monitor"):
        calls = []
        ctl = self.ctl
        with patch.object(ctl, "apply_htb", side_effect=lambda m: calls.append(("htb", m)) or True), \
             patch.object(ctl, "publish_weights", side_effect=lambda w, m, af41_w1=None: calls.append(("publish", w[0]))), \
             patch.object(ctl, "notify_te_monitor", side_effect=lambda: calls.append(("notify",)) or True), \
             patch.object(ctl, "wait_routes", side_effect=lambda e: calls.append(("wait", e[41])) or 0.3), \
             patch.object(ctl, "apply_route", side_effect=lambda m, l, a=None: calls.append(("route", m)) or ((0, 0, 0), True)), \
             patch.object(ctl, "te_monitor_owns_routes", return_value=(owner == "te_monitor")):
            ww, ok, who = self.make()._apply_capacity(target)
        return calls, ww, ok, who

    def test_decrease_changes_route_before_htb(self):
        calls, ww, ok, who = self.run_apply(450)
        self.assertEqual(calls, [("publish", 5), ("notify",), ("wait", 5), ("htb", 450)])
        self.assertEqual((ww, ok, who), ((5, 100, 100), True, "te_monitor"))

    def test_increase_widens_htb_before_route(self):
        calls, _, _, _ = self.run_apply(1441)
        self.assertEqual(calls, [("htb", 1441), ("publish", 16), ("notify",), ("wait", 16)])

    def test_self_owner_writes_route_first_when_decreasing(self):
        calls, _, _, who = self.run_apply(450, owner="self")
        self.assertEqual(calls, [("route", 450), ("htb", 450)])
        self.assertEqual(who, "self")

    def test_plain_P_keeps_old_order(self):
        args = self.ctl.parse_args([])
        c = self.ctl.Controller(args, "16005", csv.writer(open(os.devnull, "w")))
        c.current = 1171
        calls = []
        with patch.object(self.ctl, "apply_htb", side_effect=lambda m: calls.append("htb") or True), \
             patch.object(self.ctl, "notify_te_monitor", side_effect=lambda: calls.append("notify")), \
             patch.object(self.ctl, "te_monitor_owns_routes", return_value=True):
            c._apply_capacity(450)
        self.assertEqual(calls, ["htb"])                   # P は知らせない (重みは次の読み込みで変わる)

    def test_capacity_from_efficiency_table(self):
        hops = [{"connected": True, "tx_phy_mbps": 4620.0, "tx_mcs": 12},
                {"connected": True, "tx_phy_mbps": 2502.5, "tx_mcs": 9}]
        self.assertAlmostEqual(self.ctl.chain_capacity(hops, {12: 0.568}), 2502.5 * 0.52)   # 表にない MCS は 0.52
        self.assertAlmostEqual(self.ctl.chain_capacity(hops, {12: 0.568, 9: 0.86}), 2502.5 * 0.86)
        self.assertAlmostEqual(self.ctl.chain_capacity(hops, {9: 0.95, 12: 0.4}), 4620 * 0.4)    # 小さいほうの区間

    def test_efficiency_file_skips_notes(self):
        t = self.ctl.load_efficiency(str(SCRIPTS / "radwin_mcs_efficiency.json"))
        self.assertEqual(t, {12: 0.568})

    def test_notify_writes_one_line_to_fifo(self):
        with tempfile.TemporaryDirectory() as d:
            fifo, kick = Path(d) / "fifo", Path(d) / "te_monitor.kick"
            os.mkfifo(fifo)
            kick.write_text(str(fifo))
            rd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
            try:
                with patch.object(self.ctl, "TE_KICK_FILE", str(kick)):
                    self.assertTrue(self.ctl.notify_te_monitor())
                self.assertEqual(os.read(rd, 100), b"KICK\n")
            finally:
                os.close(rd)
            with patch.object(self.ctl, "TE_KICK_FILE", str(Path(d) / "missing")):
                self.assertFalse(self.ctl.notify_te_monitor())   # 無くても例外にしない

    def test_te_monitor_publishes_fifo_and_checks_weights_before_ospf(self):
        text = (SCRIPTS / "frr_te_monitor.sh").read_text()
        self.assertIn('echo "$MONITOR_FIFO" > "$TE_KICK_FILE"', text)
        loop = text.split("while true; do", 1)[1]
        self.assertLess(loop.index("_load_weights"), loop.index("check_ospf_neighbors"))

    def test_observer_P2_restarts_controller_with_options_and_restores(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, RADWIN_WEIGHTS_FILE=str(Path(d) / "w.env"))
            o = obs.Observer(Path(d), env)
            # 偽の制御: 起動すると重みファイルを書き (最初の適用の代わり)、そのまま待つ。足された引数は無視される
            fake = ["bash", "-c", 'sleep 0.3; touch "$RADWIN_WEIGHTS_FILE"; sleep 30', "ctl"]
            o.children = {n: obs.Child(n, fake, Path(d) / "c.log", env) for n in ("controller", "te_monitor")}
            o.supervise()
            t = time.time()
            o.enter_condition("P2")
            self.assertLess(time.time() - t, 5)            # 重みファイルが書かれたら待つのをやめる
            with patch.object(obs.time, "sleep"):
                self.assertIn("--pprime", o.children["controller"].argv)
                self.assertTrue(o.children["controller"].alive())
                o.leave_condition()
                o.supervise()
            self.assertNotIn("--pprime", o.children["controller"].argv)
            self.assertTrue(o.children["controller"].alive())
            self.assertEqual(o.children["controller"].restarts, 0)
            for c in o.children.values():
                c.stop()


class Af41GuardTests(unittest.TestCase):
    """条件 P3: CR1 に乗る AF41 が溢れる確率が閾値を超える容量では、AF41 の表だけ CR1 を外す。"""

    def setUp(self):
        import radwin_wcmp_controller as ctl
        self.ctl = ctl

    def test_cap_is_rate_minus_lower_class_guarantees(self):
        self.assertAlmostEqual(self.ctl.af41_cap(1171), 1171 * 67 / 70)

    def test_risk_matches_binomial(self):
        ctl = self.ctl
        # MCS 9 (整形 1171M・重み 13): 8 本まで収まり、9 本以上は 1.54% (実機の基準計測の 1.6% と一致)
        self.assertAlmostEqual(ctl.af41_overflow_risk(1171, ctl.weights_for(1171)), 0.0154, places=4)
        # MCS 1 (180M・重み 2): 1 本まで。2 本以上は 13%
        self.assertAlmostEqual(ctl.af41_overflow_risk(180, ctl.weights_for(180)), 0.1325, places=4)
        self.assertEqual(ctl.af41_overflow_risk(180, (0, 100, 100)), 0.0)

    def test_guard_keeps_cr1_at_normal_capacity_and_removes_when_small(self):
        ctl = self.ctl
        for mbps, want in ((2162, 24), (1171, 13), (1081, 12), (450, 0), (360, 0), (180, 0)):
            self.assertEqual(ctl.af41_w1(mbps, ctl.weights_for(mbps), 0.05), want, mbps)
        self.assertIsNone(ctl.af41_w1(180, ctl.weights_for(180), None))   # 判定しない条件

    def run_p3(self, current, target):
        ctl, calls = self.ctl, []
        args = ctl.parse_args(["--pprime", "--af41-guard", "0.05"])
        c = ctl.Controller(args, "16005", csv.writer(open(os.devnull, "w")))
        c.current = current
        with patch.object(ctl, "apply_htb", side_effect=lambda m: calls.append(("htb", m)) or True), \
             patch.object(ctl, "publish_weights",
                          side_effect=lambda w, m, af41_w1=None: calls.append(("publish", w[0], af41_w1))), \
             patch.object(ctl, "notify_te_monitor", return_value=True), \
             patch.object(ctl, "wait_routes", side_effect=lambda e: calls.append(("wait", e)) or 0.3), \
             patch.object(ctl, "te_monitor_owns_routes", return_value=True):
            c._apply_capacity(target)
        return calls

    def test_p3_removes_af41_before_narrowing_htb(self):
        self.assertEqual(self.run_p3(1171, 180),
                         [("publish", 2, 0), ("wait", {41: 0, 42: 2}), ("htb", 180)])

    def test_p3_restores_af41_after_widening_htb(self):
        self.assertEqual(self.run_p3(180, 1171),
                         [("htb", 1171), ("publish", 13, 13), ("wait", {41: 13, 42: 13})])

    def test_publish_writes_af41_line_only_when_given(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "w.env"
            with patch.object(self.ctl, "WEIGHTS_FILE", str(f)):
                self.ctl.publish_weights((2, 100, 100), 180, af41_w1=0)
                self.assertIn("W1_AF41=0\n", f.read_text())
                self.ctl.publish_weights((2, 100, 100), 180)
                self.assertNotIn("W1_AF41", f.read_text())

    def test_apply_weights_drops_cr1_only_from_table_41(self):
        cmds = []
        with patch.object(self.ctl, "sh", side_effect=lambda c: cmds.append(c) or (0, "")), \
             patch.object(self.ctl, "path_labels", return_value=["16005"] * 3):
            self.ctl.apply_weights((2, 100, 100), "16005", af41_w1=0)
        by_table = {c[c.index("table") + 1]: " ".join(c) for c in cmds}
        self.assertNotIn("leri-cr1", by_table["41"])
        self.assertIn("leri-cr1 weight 2", by_table["42"])
        self.assertIn("leri-cr1 weight 2", by_table["43"])

    def load_weights_in_bash(self, content):
        text = (SCRIPTS / "frr_te_monitor.sh").read_text()
        func = re.search(r"^_load_weights\(\) \{.*?^\}", text, re.S | re.M).group(0)
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "w.env"
            if content is not None:
                f.write_text(content.replace("NOW", str(int(time.time()))))
            script = (f'log() {{ :; }}; WEIGHTS_FILE={f}; WEIGHTS_MAX_AGE=30; WCMP_W1=6; WCMP_W2=25; WCMP_W3=25\n'
                      f'{func}\n_load_weights; echo "$_dw1 $_dw1a"')
            return subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout.split()

    def test_te_monitor_reads_af41_weight(self):
        self.assertEqual(self.load_weights_in_bash("TS=NOW\nW1=2\nW2=100\nW3=100\nW1_AF41=0\n"), ["2", "0"])
        self.assertEqual(self.load_weights_in_bash("TS=NOW\nW1=13\nW2=100\nW3=100\n"), ["13", "13"])
        self.assertEqual(self.load_weights_in_bash("TS=1\nW1=2\nW2=100\nW3=100\nW1_AF41=0\n"), ["6", "6"])  # 古い
        self.assertEqual(self.load_weights_in_bash(None), ["6", "6"])

    def test_te_monitor_keeps_af41_route_when_wired_paths_are_down(self):
        text = (SCRIPTS / "frr_te_monitor.sh").read_text()
        self.assertIn('if [ -z "$_nh41" ] && [ -n "$_nh" ]; then', text)

    def test_observer_condition_p3(self):
        import radwin_observe as ob
        self.assertIn("P3", ob.CONDITIONS)
        self.assertEqual(ob.PPRIME_ARGS["P3"][-2:], ["--af41-guard", "0.05"])


class ShortProbeTests(unittest.TestCase):
    """veth の確認を短くする設定 (--probe-seconds / --no-start-probe)。"""

    def test_probe_seconds_read_from_run_info(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "06_system").mkdir()
            self.assertEqual(obs._probe_seconds(Path(d)), 120)               # run.info なし → 既定
            (Path(d) / "06_system" / "run.info").write_text("git=x\nprobe_seconds=60\nperiod=900\n")
            self.assertEqual(obs._probe_seconds(Path(d)), 60)

    def test_start_rejects_short_probe_on_real_machine(self):
        text = (SCRIPTS / "radwin_observe.py").read_text()
        self.assertIn('if a.probe_seconds != PROBE_SECONDS and not a.fake_odu_dir:', text)

    def test_pprimetest_uses_short_probe(self):
        text = (SCRIPTS / "radwin_observe_pprimetest.sh").read_text()
        self.assertIn("--probe-seconds 60 --no-start-probe", text)
        self.assertNotIn("sleep 200", text)



class HoldDownTests(unittest.TestCase):
    """条件 P4: 途切れ途切れの無線で、戻ってもしばらく CR1 へ流し直さない。"""

    def setUp(self):
        import radwin_wcmp_controller as ctl
        self.ctl = ctl

    def make(self, hold):
        args = self.ctl.parse_args(["--pprime", "--af41-guard", "0.05", "--hold-down", str(hold)])
        c = self.ctl.Controller(args, "16005", csv.writer(open(os.devnull, "w")))
        c.current = 180
        return c

    def test_up_waits_for_hold_after_down(self):
        c = self.make(10)
        c.last_down = time.time() - 3
        c.up_streak = 2
        with patch.object(self.ctl, "apply_htb", return_value=True), \
             patch.object(self.ctl, "te_monitor_owns_routes", return_value=True), \
             patch.object(self.ctl, "publish_weights"), patch.object(self.ctl, "notify_te_monitor"), \
             patch.object(self.ctl, "wait_routes", return_value=0.3):
            row = c._on_normal(1301.3, {}, {})
            self.assertTrue(row[-1].startswith("up_hold"), row[-1])
            self.assertEqual(c.current, 180)                   # 上げていない
            c.last_down = time.time() - 11
            row = c._on_normal(1301.3, {}, {})
            self.assertEqual(row[-1], "up")
            self.assertEqual(c.current, 1171)

    def test_flapping_readings_do_not_raise_until_ten_seconds_of_good_readings(self):
        """2 秒ごとの読み取りが「低い・よい・よい・よい・低い…」と揺れる間は上げない (veth flaptest の再現)。"""
        c = self.make(10)
        clock = [0.0]
        seq = ["lo", "hi", "hi", "hi", "lo", "hi", "hi", "hi", "lo"] + ["hi"] * 6
        acts = []
        with patch.object(self.ctl.time, "time", side_effect=lambda: clock[0]), \
             patch.object(self.ctl, "apply_htb", return_value=True), \
             patch.object(self.ctl, "te_monitor_owns_routes", return_value=True), \
             patch.object(self.ctl, "publish_weights"), patch.object(self.ctl, "notify_te_monitor"), \
             patch.object(self.ctl, "wait_routes", return_value=0.3):
            for k, v in enumerate(seq):
                clock[0] = 2.0 * k
                acts.append(c._on_normal(200.0 if v == "lo" else 1301.3, {}, {})[-1])
        first_up = acts.index("up")
        self.assertEqual(first_up, 13)                         # 最後の低い読み取り (16 秒) の 10 秒後 = 26 秒
        self.assertGreaterEqual(2.0 * first_up - 16.0, 10)
        self.assertNotIn("up", acts[:first_up])

    def test_without_hold_up_is_unchanged(self):
        c = self.make(0)
        c.last_down = time.time()
        c.up_streak = 2
        with patch.object(self.ctl, "apply_htb", return_value=True), \
             patch.object(self.ctl, "te_monitor_owns_routes", return_value=True), \
             patch.object(self.ctl, "publish_weights"), patch.object(self.ctl, "notify_te_monitor"), \
             patch.object(self.ctl, "wait_routes", return_value=0.3):
            self.assertEqual(c._on_normal(1301.3, {}, {})[-1], "up")

    def test_recovery_after_link_down_also_waits(self):
        c = self.make(10)
        c.link_down, c.recover_streak = True, 2
        c.last_down = time.time() - 2
        self.assertTrue(c._on_recovering(1301.3)[-1].startswith("link_up_hold"))
        self.assertTrue(c.link_down)

    def test_hold_is_published(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "w.env"
            with patch.object(self.ctl, "WEIGHTS_FILE", str(f)):
                c = self.make(10)
                c._publish()
                self.assertIn("HOLD=10\n", f.read_text())
                c.link_down = True
                c._publish()
                self.assertIn("HOLD=10\n", f.read_text())        # 外している間も伝える

    def run_neighbor_checks(self, seq, hold):
        """te_monitor の check_ospf_neighbors を、隣接の状態の列 seq [(秒, Full か)] で動かす。"""
        text = (SCRIPTS / "frr_te_monitor.sh").read_text()
        func = re.search(r"^_ospf_poll_last=0\n.*?^\}", text, re.S | re.M).group(0)
        steps = " ".join(f"{t}:{int(full)}" for t, full in seq)
        script = f"""
LOG=""; log() {{ LOG="$LOG|$*"; }}; update_tables() {{ LOG="$LOG|UPDATE state0=${{state[0]}}"; }}
CR_NAMES=(CR1 CR2 CR3); CR_ROUTER_IDS=(a b c); state=(0 0 0); _dhold={hold}; _path_side=x
_fetch_neighbors() {{ :; }}
_path_full_cached() {{ [ "$1" != a ] || [ "$CUR" = 1 ]; }}
date() {{ echo "$NOW"; }}
{func}
for s in {steps}; do NOW=${{s%%:*}}; CUR=${{s##*:}}; check_ospf_neighbors; done
echo "$LOG"
"""
        return subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout

    def test_te_monitor_restores_cr1_only_after_stable(self):
        # 10 秒に消える → 12 秒に戻る → 15 秒にまた消える → 17 秒に戻る → 28 秒まで Full
        seq = [(10, 0), (12, 1), (13, 1), (15, 0), (17, 1), (20, 1), (26, 1), (28, 1)]
        log = self.run_neighbor_checks(seq, 10)
        self.assertEqual(log.count("UPDATE state0=0"), 1)          # 戻したのは 1 回だけ
        self.assertIn("再び消失", log)
        self.assertLess(log.index("安定するまで"), log.index("UPDATE state0=0"))
        self.assertTrue(log.rstrip().endswith("UPDATE state0=0"))   # 17 + 10 = 27 秒以降の 28 秒で戻す

    def test_te_monitor_without_hold_restores_at_once(self):
        log = self.run_neighbor_checks([(10, 0), (12, 1), (15, 0), (17, 1)], 0)
        self.assertEqual(log.count("UPDATE state0=0"), 2)

    def test_te_monitor_reads_hold(self):
        text = (SCRIPTS / "frr_te_monitor.sh").read_text()
        func = re.search(r"^_load_weights\(\) \{.*?^\}", text, re.S | re.M).group(0)
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "w.env"
            for content, want in ((f"TS={int(time.time())}\nW1=2\nW2=100\nW3=100\nHOLD=10\n", "10"),
                                  (f"TS={int(time.time())}\nW1=2\nW2=100\nW3=100\n", "0"),
                                  ("TS=1\nW1=2\nW2=100\nW3=100\nHOLD=10\n", "0")):   # 古いファイルは使わない
                f.write_text(content)
                script = (f'log() {{ :; }}; WEIGHTS_FILE={f}; WEIGHTS_MAX_AGE=30\n{func}\n'
                          '_load_weights; echo "$_dhold"')
                out = subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout.strip()
                self.assertEqual(out, want, content)

    def test_observer_condition_p4(self):
        self.assertIn("P4", obs.CONDITIONS)
        self.assertEqual(obs.PPRIME_ARGS["P4"][-4:], ["--af41-guard", "0.05", "--hold-down", "10"])


class FaultAnalysisTests(unittest.TestCase):
    """集計: 遮られた区間の判定 (ping も使う) と、区間の損失・新しい記録。"""

    def setUp(self):
        sys.path.insert(0, str(SCRIPTS.parent / "results" / "frr" / "tools"))
        import summarize_rain_observation as sm
        self.sm = sm

    def test_detect_event_pairs_by_time_even_when_reads_are_missing(self):
        t0 = 1000.0
        odu = [{"time": str(t0 - 100), "odu": ip, "signal_dbm": "-55", "connected": "1"}
               for ip in ("192.168.1.31", "192.168.1.32")]
        # .32 は最初の 2 回の読み取りが抜けている (以前は並び順で組んでいたので、ここで全部ずれた)
        for k, t in enumerate((10, 15, 20, 25)):
            odu.append({"time": str(t0 + t), "odu": "192.168.1.31", "signal_dbm": "-70", "connected": "1"})
            if k >= 2:
                odu.append({"time": str(t0 + t + 1), "odu": "192.168.1.32", "signal_dbm": "-70", "connected": "1"})
        ev = self.sm.detect_event(odu, [], [], t0, t0 + 120)
        self.assertEqual(ev["event"], 1)
        self.assertEqual(ev["event_hop"], "無線1")

    def test_detect_event_from_ping_only(self):
        t0 = 1000.0
        ping = [{"time": str(t0 + t), "status": "no_answer"} for t in (30, 33, 40)]
        ev = self.sm.detect_event([], [], ping, t0, t0 + 120)
        self.assertEqual((ev["event"], ev["event_hop"], ev["event_drop_db"]), (1, "ping", "ping のみ"))
        self.assertEqual(round(ev["event_t1"] - ev["event_t0"]), 11)
        lone = [{"time": str(t0 + 30), "status": "no_answer"}, {"time": str(t0 + 80), "status": "timeout"}]
        self.assertEqual(self.sm.detect_event([], [], lone, t0, t0 + 120)["event"], 0)   # 離れた 1 回ずつは数えない

    def test_interval_loss_takes_first_sum_line(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "iperf3_af41.log"
            f.write_text("[SUM]   0.00-1.00   sec  1 GBytes  8 Gbits/sec  0.05 ms  5/142000 (0%)\n"
                         "[SUM]   1.00-2.00   sec  1 GBytes  8 Gbits/sec  0.05 ms  7/142000 (0%)\n"
                         "[SUM]   0.00-120.00 sec  1 GBytes  8 Gbits/sec  0.05 ms  12/17000000 (0%)  receiver\n"
                         "[SUM]   1.00-2.00   sec  1 GBytes  8 Gbits/sec  0.05 ms  99/142000 (0%)\n")
            self.assertEqual(self.sm.iperf_interval_lost(f), {0: 5, 1: 7})

    def test_extra_drops(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "rx_drops.csv").write_text("time,node,counter,per_sec\n1,Rx1,udp.RcvbufErrors,3\n"
                                            "2,Rx1,udp.RcvbufErrors,4\n1,LER_Egress,lere-cr2.rx_drop,2\n"
                                            "1,Rx1,udp.InDatagrams,99\n")
            (d / "tc_drops.csv").write_text("time,node,iface,class,drops_per_sec\n1,CR2,cr2-lere,AF41,0\n"
                                            "1,CR2,cr2-lere,AF42,50\n1,LER_Ingress,leri-cr1,AF41,9\n")
            (d / "route_state.csv").write_text("time,cr1_label_dev,leri_label_dev,leri_from_cr1_bytes_per_sec\n"
                                               "1,cr1-lere,leri-cr1,100\n2,cr1-leri,leri-cr2+leri-cr3,250000000\n")
            r = self.sm.extra_drops(d)
            self.assertEqual((r["rx_rcvbuf"], r["lere_rx_drop"], r["cr23_af41_drop"], r["hairpin_s"],
                              r["hairpin_max_mbps"]), (7, 2, 0, 1, 2000))

    def test_measure_records_new_files(self):
        text = (SCRIPTS / "frr_measure.sh").read_text()
        for name in ("rx_drops.csv", "route_state.csv", "route_events.log", '"CR2:$CR2_PID:cr2-lere"', '"CR3:$CR3_PID:cr3-lere"',
                     'kill "${RX_MONITOR_PID:-}"'):
            self.assertIn(name, text)


class AdjacencySidTests(unittest.TestCase):
    """案 A: 有線の経路 (CR2/CR3) は LER_Egress への隣接 SID で送る (Node SID の入れ直しを避ける)。"""

    LFIB = ("15000 via inet 10.0.4.2 dev cr2-lere proto ospf\n"
            "15001 via inet 10.0.4.2 dev cr2-lere proto ospf\n"
            "15002 via inet 10.0.3.1 dev cr2-leri proto ospf\n"
            "16005 as to 16005 via inet 10.0.4.2 dev cr2-lere proto ospf\n")

    def setUp(self):
        import radwin_wcmp_controller as ctl
        self.ctl = ctl

    def test_controller_reads_adjacency_sid(self):
        with patch.object(self.ctl, "sh", return_value=(0, self.LFIB)):
            self.assertEqual(self.ctl.adj_label("CR2", "10.0.4.2", "cr2-lere"), "15000")
            self.assertIsNone(self.ctl.adj_label("CR3", "10.0.6.2", "cr3-lere"))

    def test_path_labels_and_fallback(self):
        def fake(cmd):
            return (0, self.LFIB.replace("cr2", "cr3").replace("10.0.4.2", "10.0.6.2").replace("150", "151")
                    if "CR3" in cmd else self.LFIB)
        with patch.object(self.ctl, "sh", side_effect=fake):
            self.assertEqual(self.ctl.path_labels("16005"), ["16005", "15000", "15100"])
        with patch.object(self.ctl, "sh", return_value=(0, "")):
            self.assertEqual(self.ctl.path_labels("16005"), ["16005"] * 3)   # 読めなければ Node SID
        with patch.dict(os.environ, {"SR_WIRED_SID": "node"}), patch.object(self.ctl, "sh", side_effect=fake):
            self.assertEqual(self.ctl.path_labels("16005"), ["16005"] * 3)

    def test_get_label_ignores_adjacency_sids(self):
        t41 = ("10.20.0.0/16 proto static\n\tnexthop encap mpls 15000 via 10.0.3.2 dev leri-cr2 weight 100\n"
               "\tnexthop encap mpls 15100 via 10.0.5.2 dev leri-cr3 weight 100\n")
        with patch.object(self.ctl, "sh", return_value=(0, t41)):
            self.assertEqual(self.ctl.get_label(), "16005")
        with patch.object(self.ctl, "sh", return_value=(0, "nexthop encap mpls 16007 via x\n" + t41)):
            self.assertEqual(self.ctl.get_label(), "16007")

    def test_shell_scripts_read_adjacency_sid_the_same_way(self):
        for name, fn in (("frr_te_monitor.sh", "_adj_label"), ("frr_dscp_te.sh", "adj_label")):
            text = (SCRIPTS / name).read_text()
            func = re.search(rf"^{fn}\(\) \{{.*?^\}}", text, re.S | re.M).group(0)
            # docker exec / dc を、転送表を出すだけの偽物に置き換えて動かす
            script = (f'docker() {{ printf "%s" "$LFIB"; }}; dc() {{ printf "%s" "$LFIB"; }}\n{func}\n'
                      f'{fn} CR2 10.0.4.2 cr2-lere; echo; {fn} CR2 10.0.6.2 cr3-lere; echo')
            out = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                                 env=dict(os.environ, LFIB=self.LFIB)).stdout.split("\n")
            self.assertEqual(out[:2], ["15000", ""], name)

    def test_cr_egress_classifies_plain_ip_too(self):
        text = (SCRIPTS / "frr_dscp_te.sh").read_text()
        for tos, cls in (("0x88", "1:1"), ("0x90", "1:2"), ("0x98", "1:3")):
            self.assertIn(f"u32 match ip dsfield {tos} 0xfc flowid {cls}", text)


class FaultPlanTests(unittest.TestCase):
    """金属板の実験: 条件の順番の入れ替えと、外す合図。"""

    def test_runs_without_shuffle_keep_order(self):
        self.assertEqual(obs.fault_runs(["P", "P4"], 2), ["P", "P4", "P", "P4"])

    def test_shuffle_has_each_condition_once_per_round_and_is_reproducible(self):
        conds = ["P", "P3", "P4", "S", "N"]
        runs = obs.fault_runs(conds, 3, seed=12345)
        for k in range(3):
            self.assertEqual(sorted(runs[5 * k:5 * k + 5]), sorted(conds))
        self.assertEqual(runs, obs.fault_runs(conds, 3, seed=12345))     # 種から同じ順番を再現できる
        self.assertNotEqual(runs, conds * 3)

    def test_fault_has_duration_and_shuffle_options(self):
        text = (SCRIPTS / "radwin_observe.py").read_text()
        for s in ('"--shuffle"', '"--duration"', "← 今、置く", "← 今、外す", "fault_plan.csv"):
            self.assertIn(s, text)
