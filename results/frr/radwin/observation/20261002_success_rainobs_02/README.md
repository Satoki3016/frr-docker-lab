# 雨の観測の記録

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
