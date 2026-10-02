#!/usr/bin/env python3
"""実験場所の雨の強さを、気象庁の高解像度降水ナウキャスト (実況) から 5 分ごとに記録する。

アメダス名古屋は実験場所から約 3.7 km 離れ、10 分ごと・0.5 mm 単位でしか分からない。
ナウキャストはレーダーと雨量計から作る 5 分ごとの降水強度で、陸上では約 250 m 四方の細かさがある。
地図タイル (PNG) の色が強さの階級を表すので、実験場所の画素の色を読む。

  データ: https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N1.json (実況の時刻一覧。UTC)
          https://www.jma.go.jp/bosai/jmatile/data/nowc/{basetime}/none/{validtime}/surf/hrpns/{z}/{x}/{y}.png
  色と階級 (気象庁のナウキャストの凡例。2026-10-02 に全国のタイルでこの 8 色だけが現れることを確認):
      0〜1 / 1〜5 / 5〜10 / 10〜20 / 20〜30 / 30〜50 / 50〜80 / 80〜 [mm/h]
  透明 = 降水なし。表にない色は "unknown" として色の値をそのまま残す。

記録: <観測フォルダ>/nowcast_YYYYMMDD.csv
  time            取得した時刻 (UNIX 秒)
  valid_jst       ナウキャストの対象時刻 (日本時間)
  mmh_lo / mmh_hi 実験場所の画素の階級 (降水なしは 0 / 0)
  area_max_hi     実験場所から約 ±300 m (5×5 画素) の中の最も強い階級の上限 (雨域の端にいるときの手がかり)
  rgba            実験場所の画素の色 (検証用)
場所は RADWIN_SITE_LAT / RADWIN_SITE_LON で変えられる (既定は実験場所。北緯 35.1566661 度 東経 136.9263615 度)。

使い方 (通常は radwin_observe.py が起動する):
    sudo python3 scripts/radwin_nowcast.py --dir <観測フォルダ>
    python3 scripts/radwin_nowcast.py --once          # 今の値を表示するだけ
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import math
import os
import signal
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from radwin_odu_logger import append_rows, daily_path  # noqa: E402

BASE = "https://www.jma.go.jp/bosai/jmatile/data/nowc"
ZOOM = 10                     # 1 画素は北緯 35 度で約 125 m
SITE_LAT = float(os.environ.get("RADWIN_SITE_LAT", "35.1566661"))
SITE_LON = float(os.environ.get("RADWIN_SITE_LON", "136.9263615"))
PALETTE = {                   # (R, G, B) → (下限, 上限) [mm/h]。上限 None は「以上」
    (242, 242, 255): (0, 1), (160, 210, 255): (1, 5), (33, 140, 255): (5, 10),
    (0, 65, 255): (10, 20), (250, 245, 0): (20, 30), (255, 153, 0): (30, 50),
    (255, 40, 0): (50, 80), (180, 0, 104): (80, None),
}
COLUMNS = ["time", "valid_jst", "mmh_lo", "mmh_hi", "area_max_hi", "rgba", "lat", "lon", "error"]
JST = dt.timezone(dt.timedelta(hours=9))


def _get(url: str, timeout: float = 20.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "radwin-observe (lab research)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def tile_pixel(lat: float, lon: float, z: int = ZOOM) -> tuple[int, int, int, int]:
    """緯度経度 → (タイル x, タイル y, 画素 x, 画素 y)。Web メルカトル。"""
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return int(x), int(y), int((x % 1) * 256), int((y % 1) * 256)


def classify(rgba: tuple) -> tuple:
    """画素の色 → (下限, 上限)。透明は (0, 0)、表にない色は None。"""
    if rgba[3] == 0:
        return (0, 0)
    return PALETTE.get(tuple(rgba[:3]))


def collect(lat: float = SITE_LAT, lon: float = SITE_LON) -> dict:
    from PIL import Image
    row = {c: "" for c in COLUMNS}
    row.update(time=f"{time.time():.3f}", lat=lat, lon=lon)
    try:
        latest = json.loads(_get(f"{BASE}/targetTimes_N1.json"))[0]     # 先頭が最新の実況
        b, v = latest["basetime"], latest["validtime"]
        row["valid_jst"] = (dt.datetime.strptime(v, "%Y%m%d%H%M%S").replace(tzinfo=dt.timezone.utc)
                            .astimezone(JST).strftime("%Y-%m-%dT%H:%M"))
        tx, ty, px, py = tile_pixel(lat, lon)
        im = Image.open(io.BytesIO(_get(f"{BASE}/{b}/none/{v}/surf/hrpns/{ZOOM}/{tx}/{ty}.png"))).convert("RGBA")
        rgba = im.getpixel((px, py))
        row["rgba"] = "%d-%d-%d-%d" % rgba
        c = classify(rgba)
        if c is None:
            row["mmh_lo"] = row["mmh_hi"] = "unknown"
        else:
            row["mmh_lo"], row["mmh_hi"] = c[0], ("" if c[1] is None else c[1])
        # 周囲 5×5 画素 (タイルの端では切り詰める)。上限 None (80 以上) は 999 として比べる
        his = []
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                qx, qy = px + dx, py + dy
                if 0 <= qx < 256 and 0 <= qy < 256:
                    k = classify(im.getpixel((qx, qy)))
                    if k is not None:
                        his.append(999 if k[1] is None else k[1])
        row["area_max_hi"] = max(his) if his else ""
    except Exception as e:                  # ネットワーク断などで記録を止めない
        row["error"] = str(e)[:200]
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dir", help="観測フォルダ。nowcast_YYYYMMDD.csv に追記し続ける")
    g.add_argument("--once", action="store_true", help="今の値を表示するだけ")
    ap.add_argument("--interval", type=float, default=300.0)
    a = ap.parse_args()
    if a.once:
        print(json.dumps(collect(), ensure_ascii=False))
        return 0
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    try:
        while not stop:
            row = collect()
            append_rows(daily_path(Path(a.dir), "nowcast", float(row["time"])), COLUMNS,
                        [[row[c] for c in COLUMNS]])
            end = time.monotonic() + a.interval
            while not stop and time.monotonic() < end:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
