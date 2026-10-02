#!/usr/bin/env python3
"""雨の観測のための気象データを、気象庁アメダス (名古屋) などから集める。

使い道:
    --dir <観測フォルダ>             10 分ごとに weather_YYYYMMDD.csv へ追記し続ける (radwin_observe.py が起動)
    --snapshot <ファイル.json>       今の値を 1 回だけ取り、JSON に書く (全負荷計測の終了時に使う)

データの出どころ:
  ■ 気象庁アメダス 名古屋 (地点番号 51106、北緯35度10.0分 東経136度57.9分、千種区)
    実験場所 (北緯35.1566661度 東経136.9263615度) から約 3.7 km。昭和区内にアメダスは無い。
    https://www.jma.go.jp/bosai/amedas/data/point/51106/YYYYMMDD_HH.json (3 時間ごとのファイルに 10 分値)
    取る要素 (各要素は [値, 品質フラグ]。フラグ 0 = 正常。0 以外は値を残し、フラグも記録する):
      weather            自動観測による天気 (毎正時のみ)。0 晴 / 1 曇 / 2 煙霧 / 3 霧 / 4 降水 / 5 霧雨 /
                         6 着氷性の霧雨 / 7 雨 / 8 着氷性の雨 / 9 みぞれ / 10 雪 / 11 凍雨 / 12 霧雪 /
                         13 しゅう雨または止み間のある雨 / 14 しゅう雪… / 15 ひょう / 16 雷
      temp [℃] / humidity [%]       → 露点 [℃] を計算する (窓の結露の判断に使う)
      precipitation10m / 1h / 3h [mm]  0.5 mm 単位 (10 分値の 0.5 mm は 3 mm/h に当たる。弱い雨は 0 になりうる)
      wind [m/s]、windDirection (16 方位。1 北北東 … 16 北、0 静穏)
                         → 雨が窓に当たるかは風向で変わる。強い風は三脚の揺れ (向きのずれ) の手がかり
                         (10 分値の gust はその日の最大瞬間風速 (gustTime 付き) で、その時刻の値ではないので取らない)
      sun10m [分]        日照 (窓の乾きやすさ、昼夜)
      visibility [m]     視程 (霧)
      pressure [hPa]     現地気圧
  ■ Open-Meteo (実験場所の座標での数値モデルの推定値。観測ではない)
    weather_code (WMO)、precipitation、cloud_cover。アメダスと場所が離れているので補助として残す。
コード表と品質フラグの意味は、気象庁の配信資料「自動観測による天気」「観測値の AQC 識別符」に基づく
(https://qiita.com/KAI_Mutsumi/items/79b169d0b8ed3135cd1a で確認)。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import signal
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from radwin_odu_logger import append_rows, daily_path  # noqa: E402

AMEDAS = "51106"
JMA = "https://www.jma.go.jp/bosai/amedas/data"
SITE_LAT, SITE_LON = 35.1566661, 136.9263615   # 実験場所 (窓のある建物。2026-10-02 にユーザーが指定)
OPEN_METEO = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
              "&current=weather_code,precipitation,cloud_cover&timezone=Asia%2FTokyo")
JST = dt.timezone(dt.timedelta(hours=9))

WEATHER = ["晴", "曇", "煙霧", "霧", "降水", "霧雨", "着氷性の霧雨", "雨", "着氷性の雨", "みぞれ",
           "雪", "凍雨", "霧雪", "しゅう雨または止み間のある雨", "しゅう雪または止み間のある雪", "ひょう", "雷"]
DIRS = ["静穏", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東", "南",
        "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西", "北"]
ELEMS = ["temp", "humidity", "precipitation10m", "precipitation1h", "precipitation3h",
         "wind", "windDirection", "sun10m", "visibility", "pressure"]
COLUMNS = (["time", "obs_time"] + ELEMS + ["dew_point", "wind_dir_name",
           "weather_time", "weather", "weather_name", "flags",
           "om_time", "om_weather_code", "om_precipitation", "om_cloud_cover", "error"])


def _get(url: str, timeout: float = 20.0):
    req = urllib.request.Request(url, headers={"User-Agent": "radwin-observe (lab research)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


def dew_point(t: float, rh: float) -> float:
    """Magnus 式 (a=17.62, b=243.12 ℃) による露点 [℃]。"""
    g = math.log(rh / 100.0) + 17.62 * t / (243.12 + t)
    return 243.12 * g / (17.62 - g)


def amedas_records(latest: dt.datetime) -> dict:
    """latest を含む 3 時間ファイルと、その 1 つ前のファイル (毎正時の天気を探すため) を読む。"""
    recs = {}
    for back in (3, 0):
        t = latest - dt.timedelta(hours=back)
        name = f"{t:%Y%m%d}_{t.hour // 3 * 3:02d}"
        try:
            recs.update(json.loads(_get(f"{JMA}/point/{AMEDAS}/{name}.json")))
        except Exception:
            if back == 0:
                raise
    return recs


def collect() -> dict:
    """今の値を 1 組取る。取れなかった部分は空欄にし、理由を error に書く。"""
    row = {c: "" for c in COLUMNS}
    row["time"] = f"{time.time():.3f}"
    errors = []
    try:
        latest = dt.datetime.fromisoformat(_get(f"{JMA}/latest_time.txt").strip())
        recs = amedas_records(latest)
        key = f"{latest:%Y%m%d%H%M%S}"
        r = recs.get(key) or recs[max(recs)]
        key = key if key in recs else max(recs)
        row["obs_time"] = f"{dt.datetime.strptime(key, '%Y%m%d%H%M%S').replace(tzinfo=JST):%Y-%m-%dT%H:%M}"
        flags = []
        for e in ELEMS:
            if e in r:
                v, f = r[e]
                row[e] = "" if v is None else v
                if f:
                    flags.append(f"{e}={f}")
        if row["temp"] != "" and row["humidity"] not in ("", 0):
            row["dew_point"] = round(dew_point(float(row["temp"]), float(row["humidity"])), 1)
        if row["windDirection"] != "":
            row["wind_dir_name"] = DIRS[int(row["windDirection"])]
        hourly = [k for k in sorted(recs) if k <= key and "weather" in recs[k]]
        if hourly:
            k = hourly[-1]
            v, f = recs[k]["weather"]
            row["weather_time"] = f"{dt.datetime.strptime(k, '%Y%m%d%H%M%S'):%Y-%m-%dT%H:%M}"
            row["weather"] = "" if v is None else v
            row["weather_name"] = WEATHER[v] if isinstance(v, int) and 0 <= v < len(WEATHER) else ""
            if f:
                flags.append(f"weather={f}")
        row["flags"] = " ".join(flags)
    except Exception as e:                       # ネットワーク断などで記録を止めない
        errors.append(f"amedas: {e}")
    try:
        cur = json.loads(_get(OPEN_METEO.format(lat=SITE_LAT, lon=SITE_LON)))["current"]
        row.update(om_time=cur.get("time", ""), om_weather_code=cur.get("weather_code", ""),
                   om_precipitation=cur.get("precipitation", ""), om_cloud_cover=cur.get("cloud_cover", ""))
    except Exception as e:
        errors.append(f"open-meteo: {e}")
    row["error"] = "; ".join(errors)
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dir", help="観測フォルダ。weather_YYYYMMDD.csv に追記し続ける")
    g.add_argument("--snapshot", help="今の値を 1 回だけ JSON に書く")
    ap.add_argument("--interval", type=float, default=600.0)
    a = ap.parse_args()
    if a.snapshot:
        row = collect()
        # 全負荷計測ごとの記録には、実験場所のナウキャスト (radwin_nowcast.py) も入れる
        from radwin_nowcast import collect as nowcast
        nc = nowcast()
        row.update({f"nc_{k}": v for k, v in nc.items() if k in ("valid_jst", "mmh_lo", "mmh_hi", "area_max_hi", "rgba")})
        if nc.get("error"):
            row["error"] = "; ".join(x for x in (row["error"], f"nowcast: {nc['error']}") if x)
        Path(a.snapshot).write_text(json.dumps(row, ensure_ascii=False, indent=1))
        return 0
    folder = Path(a.dir)
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    try:
        while not stop:
            row = collect()
            append_rows(daily_path(folder, "weather", float(row["time"])), COLUMNS,
                        [[row[c] for c in COLUMNS]])
            end = time.monotonic() + a.interval
            while not stop and time.monotonic() < end:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
