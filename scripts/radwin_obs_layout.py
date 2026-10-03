#!/usr/bin/env python3
"""雨の観測フォルダの中の並べ方 (2026-10-03 から)。観測・検査・集計・整理が共通で使う。

    <観測フォルダ>/
      README.md       このフォルダの案内 (何がどこにあるか)
      01_report/      まず見るところ。途中経過の報告書・集計表・時系列の図
      02_fullload/    全負荷計測。一覧 (probes.csv) と 1 回ごとのフォルダ
      03_radio/       無線の記録。4 台の ODU (odu_*.csv) と ping (ping_*.csv)
      04_control/     制御と経路の記録。controller.csv・state_*.csv・ospf_bfd_*.csv・te_monitor.log
      05_weather/     気象。アメダス (weather_*.csv) と実験場所のナウキャスト (nowcast_*.csv)
      06_system/      観測の運転の記録。events.csv・check.txt・status.json・run.info・各部品の画面出力

2026-10-03 より前の観測は、すべてをフォルダの直下に置いていた。organize() で上の形に移せる。
読む側 (find) はどちらの形でも読める。

使い方 (止めた観測フォルダを整理する):
    python3 scripts/radwin_obs_layout.py <観測フォルダ>
"""
from __future__ import annotations

import fnmatch
import shutil
import sys
from pathlib import Path

REPORT, FULLLOAD, RADIO, CONTROL, WEATHER, SYSTEM = (
    "01_report", "02_fullload", "03_radio", "04_control", "05_weather", "06_system")

# 古い形 (直下) のファイル → 新しい形の置き場所
_RULES = [
    ("odu_*.csv", RADIO), ("ping_*.csv", RADIO),
    ("controller.csv", CONTROL), ("state_*.csv", CONTROL), ("ospf_bfd_*.csv", CONTROL),
    ("te_monitor.log", CONTROL),
    ("weather_*.csv", WEATHER), ("nowcast_*.csv", WEATHER),
    ("probes.csv", FULLLOAD),
    ("judgement.txt", REPORT),
    ("events.csv", SYSTEM), ("check.txt", SYSTEM), ("status.json", SYSTEM), ("run.info", SYSTEM),
    ("*.log", SYSTEM), ("vethtest_marks.csv", SYSTEM),
]

README = """# 雨の観測の記録

フォルダ名の `running` は観測中、`success` は止めたあと (計測として正常に完了) を表す。
時刻の列 `time` は UNIX 秒 (日本時間に直すには集計スクリプトを使う)。

| フォルダ | 中身 | まず見るもの |
|---|---|---|
| `01_report/` | 途中経過の報告書 (6 時間ごと)、集計表、時系列の図 | `latest_report.md` |
| `02_fullload/` | 全負荷計測 (3 クラス × 8 Gbps を 120 秒)。一覧と 1 回ごとのフォルダ | `probes.csv` |
| `03_radio/` | 4 台の ODU の受信電力・MCS など (5 秒ごと)、無線区間の ping (1 秒ごと) | `odu_YYYYMMDD.csv` |
| `04_control/` | 動的制御 (2 秒ごと)、経路表と HTB (10 秒)、OSPF/BFD (60 秒)、te_monitor の記録 | `controller.csv` |
| `05_weather/` | アメダス名古屋 (10 分ごと)、実験場所の降水ナウキャスト (5 分ごと) | `nowcast_YYYYMMDD.csv` |
| `06_system/` | 観測の運転の記録 (部品の起動・再起動、欠測の検査、状態、各部品の画面出力) | `check.txt` |

全負荷計測 1 回のフォルダ (`02_fullload/<日付>_success_rainobs_wcmp_NN/`):
`frr_observe/throughput.csv` (各クラスの毎秒の受信量)、`frr_observe/iperf3_af41〜43.log` (送受信と損失)、
`weather.json` (その回の終了時点の気象)、`validation.txt` (合否)。

集計 (表と図を 01_report/ に作り直す。元の記録は変えない):
    python3 results/frr/tools/summarize_rain_observation.py --dir <このフォルダの名前>
"""


def is_new(obs: Path) -> bool:
    return (obs / SYSTEM).is_dir()


def sub(obs: Path, name: str) -> Path:
    """新しい形ならサブフォルダ、古い形なら直下を返す。"""
    if is_new(obs):
        return obs / name
    return obs / ("summary" if name == REPORT else "probes" if name == FULLLOAD else "")


def find(obs: Path, pattern: str) -> list[Path]:
    """直下と、1 段下のサブフォルダから探す (全負荷計測 1 回ごとのフォルダの中までは見ない)。"""
    out = list(obs.glob(pattern))
    for d in sorted(p for p in obs.iterdir() if p.is_dir()):
        out += list(d.glob(pattern))
    return sorted(set(out))


def probe_dir(obs: Path, name: str) -> Path:
    """全負荷計測 1 回のフォルダ。"""
    for base in (obs / FULLLOAD, obs / "probes"):
        if (base / name).is_dir():
            return base / name
    return obs / FULLLOAD / name


def make(obs: Path) -> None:
    """新しい観測フォルダの骨組みを作る。"""
    for d in (REPORT, FULLLOAD, RADIO, CONTROL, WEATHER, SYSTEM):
        (obs / d).mkdir(parents=True, exist_ok=True)
    (obs / "README.md").write_text(README)


def organize(obs: Path) -> list[str]:
    """古い形 (直下に全部) を新しい形に移す。何度実行してもよい。動いた内容を返す。"""
    moved = []
    for d in (REPORT, FULLLOAD, RADIO, CONTROL, WEATHER, SYSTEM):
        (obs / d).mkdir(exist_ok=True)
    old_report, old_probes = obs / "summary", obs / "probes"
    for old, new in ((old_report, obs / REPORT), (old_probes, obs / FULLLOAD)):
        if old.is_dir():
            for p in sorted(old.iterdir()):
                shutil.move(str(p), str(new / p.name))
                moved.append(f"{old.name}/{p.name} → {new.name}/")
            old.rmdir()
    for p in sorted(obs.iterdir()):
        if not p.is_file() or p.name == "README.md":
            continue
        for pat, dest in _RULES:
            if fnmatch.fnmatch(p.name, pat):
                shutil.move(str(p), str(obs / dest / p.name))
                moved.append(f"{p.name} → {dest}/")
                break
    (obs / "README.md").write_text(README)
    return moved


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    target = Path(sys.argv[1])
    if "_running_" in target.name:
        sys.exit("[NG] 観測中のフォルダは整理できません。止めてから実行してください")
    for line in organize(target):
        print(line)
    print(f"整理しました: {target}")
