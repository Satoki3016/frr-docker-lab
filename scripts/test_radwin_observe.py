#!/usr/bin/env python3
"""雨の観測 (radwin_observe.py と記録係) の、実機を操作しない回帰検証。

    python3 -m unittest discover -s scripts -p 'test_radwin_observe.py' -v
"""
from __future__ import annotations

import csv
import os
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
            ev = list(csv.DictReader((Path(d) / "events.csv").open()))
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
            pr = list(csv.DictReader((Path(d) / "probes.csv").open()))
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
            pr = list(csv.DictReader((Path(d) / "probes.csv").open()))
            self.assertEqual((pr[0]["result"], pr[0]["exit_code"]), ("success", "0"))
            ev = [e["event"] for e in csv.DictReader((Path(d) / "events.csv").open())]
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
