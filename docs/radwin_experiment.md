# RADWIN 実験ガイド

## 1. 普段使う入口

リポジトリのルートで実行します。ラッパーはC2構成を選び、既存スクリプトを呼び出します。
既存の容量推定・制御条件・送信レート・QoS・3シナリオは変更していません。

| やりたいこと | コマンド (`sudo bash scripts/radwin_experiment.sh` に続ける) |
|---|---|
| 設定を表示 | `config` (sudo不要) |
| 前提条件を確認 | `check` |
| 無線状態を1回取得 | `telemetry` |
| 起動済み環境へWCMP・QoSを適用 | `prepare` |
| 動的制御だけ実行 | `control タグ 2` |
| 3クラス計測と動的制御を同時に実行 | `run 120 タグ 2` |
| 静的WCMPで既存3シナリオを計測 | `measure 60 all タグ wcmp` |
| ECMPで既存3シナリオを計測 | `measure 60 all タグ ecmp` |

タグと制御間隔は省略可能です。タグ省略時は日時・操作・モード・PIDから名前を生成します。
指定したタグが既に存在する場合は停止します。結果への追記・上書きを避けるため、再計測には別のタグを使います。

実行するコマンドだけ確認する場合:

```bash
bash scripts/radwin_experiment.sh --plan run 120 antenna_test
bash scripts/radwin_experiment.sh --plan measure 60 all ecmp_test ecmp
```

`--plan` はネットワーク操作、ログ作成、プロセス起動を行いません。

## 2. 実験前の状態

必要な構成:

- C2のコンテナ・netns・物理配線が構築済み。
- CR1→LER_EgressはRADWIN 2ホップ、CR2・CR3は有線。
- ODUの認証ファイルは従来どおり `~/.radwin_pass`。sudo時は元ユーザーのホームも検索します。
- 実験を操作するコントローラ・計測スクリプトは1組だけ。

```bash
bash scripts/radwin_experiment.sh config
sudo bash scripts/radwin_experiment.sh prepare
sudo bash scripts/radwin_experiment.sh check
sudo bash scripts/radwin_experiment.sh telemetry
```

`prepare` は `LAB_MODE=c2 ROUTE_MODE=wcmp` で既存の `frr_dscp_te.sh` を実行します。
帯域・経路・DSCP分類を初期設定に戻す操作なので、制御・計測を止めた状態で実行します。
`check` は既存コントローラの前提検査だけです。HTBの存在、table 41の3本のnexthop、L3+L4ハッシュを検査し、失敗時は終了コード1です。無線の疎通や計測全体の健全性まで保証する検査ではありません。
`telemetry` はODUへ接続し、必要ならCR1の `cr1-lere` に管理用IPを追加します。

ラボ自体が未構築の場合に使う従来のコマンド:

```bash
sudo env LAB_MODE=c2 ROUTE_MODE=wcmp bash scripts/frr_all_up.sh
```

これは既存コンテナの削除・再作成と物理NICの再配置を行います。普段の `run` / `prepare` からは呼びません。
起動後はOSPFが収束してから `prepare` / `check` を実施してください。

## 3. アンテナ操作による容量変動実験

```bash
sudo bash scripts/radwin_experiment.sh run 120 antenna_01
```

実行順序:

1. C2 / WCMPの既存QoS設定を適用。
2. `frr_measure.sh` の `normal` シナリオで3経路を設定。
3. 経路初期化の完了後に、2秒間隔のコントローラを起動。
4. 既存のAF41・AF42・AF43計測を実行。
5. 送信終了時に、この計測が起動したコントローラを終了。
6. 既存処理でデータ回収・グラフ生成し、ストリーム数と制御ログを検査。

画面に「計測中」と出てから、正常状態→アンテナの向きを変更→元に戻す、の順で操作します。
操作時刻は別途メモしておくと、MCSと受信レートの変化を照合できます。
制御の表示は別端末から確認できます。

```bash
tail -f results/frr/radwin/dynamic/antenna_01/controller.log
```

`run` の既定は手動の容量変動を測る `normal` です。自動の20秒障害注入は行いません。
normalは既存仕様どおりTEモニターを停止しますが、無線が切れた場合は制御自身が
CR1 を経路から外します (未接続を2回連続で確認 → 重み 0)。

障害注入と動的制御を重ねる場合は、4番目の引数に `failure_reroute` を指定します (2026-09-25 追加)。

```bash
sudo bash scripts/radwin_experiment.sh run 60 reroute_01 2 failure_reroute
```

このときは TEモニターが経路表を書き、制御は重みと HTB だけを決めます
(TEモニターの pidfile `/run/radwin/te_monitor.pid` で自動判定)。
`failure` は「迂回なし」の比較用なので、動的制御とは組み合わせられません。

ケーブル抜去などの手動の障害だけで試す場合は `manual` を指定します (2026-09-25 追加)。
自動の障害注入はせず、TEモニターは起動します。操作時刻は `date +%T` で控えてください。

```bash
sudo bash scripts/radwin_experiment.sh run 180 unplug 2 manual
```

注意: `plot_frr.py` が自動生成するスループット図は単一経路を前提に値をリンク容量で頭打ちにするため、
WCMP (3経路) の計測では正しくありません。WCMP の評価は専用の解析で行ってください。

同時計測の記録は [20260918_success_dynamic_integrated](../results/frr/radwin/dynamic/20260918_success_dynamic_integrated/) にあります。
保存された検査結果は3クラス各64ストリーム、制御91サンプル、適用失敗0です。通信品質の評価には同フォルダの計測データを参照してください。

## 4. 制御だけ実行する場合

構築・設定済みの環境で:

```bash
sudo bash scripts/radwin_experiment.sh control antenna_probe_01 2
```

Ctrl+Cで停止します。ラッパーはトラフィックを生成せず、QoSの再適用もしません。
停止後は最後に適用した帯域・経路が残ります。基準値へ戻すときは `prepare` を実行します。

元のコマンドも従来どおりです:

```bash
sudo python3 scripts/radwin_wcmp_controller.py --interval 2
sudo python3 scripts/radwin_wcmp_controller.py --once
sudo python3 scripts/radwin_wcmp_controller.py --dry-run
```

直接実行時のCSVは引き続き `/tmp/radwin_controller.csv` へ追記されます。
新しい引数は `--check` (前提確認のみ) と `--log-csv 保存先` (保存先の変更) です。
`--log-csv` の親ディレクトリは事前に作成してください。
従来の `--dry-run` は経路・HTBの適用を省略しますが、テレメトリ取得とCSV記録は行います。
SSH接続に必要な管理用IPが追加される場合もあるため、読み取りだけの前提確認には `--check` を使います。

## 5. ECMP / 静的WCMP / 障害シナリオの比較

```bash
# 60秒 × normal / failure / failure_reroute
sudo bash scripts/radwin_experiment.sh measure 60 all compare_wcmp_01 wcmp
sudo bash scripts/radwin_experiment.sh measure 60 all compare_ecmp_01 ecmp

# 単一シナリオ
sudo bash scripts/radwin_experiment.sh measure 60 normal normal_wcmp_01 wcmp
sudo bash scripts/radwin_experiment.sh measure 60 failure_reroute reroute_01 wcmp

# 従来のCR1主経路方式
sudo bash scripts/radwin_experiment.sh measure 60 all primary_01 primary
```

`measure` は動的コントローラを起動しません。`all` は既存 `run_all_scenarios.sh` に委譲し、ストリーム取りこぼし時の再試行もそのまま使用します。
再試行にはTIME_WAIT解消の待機が入るため、終了まで計測秒数の3倍以上かかる場合があります。
単一シナリオは再試行しません。欠測を検出したら別タグで再計測します。

ラッパー経由の設定・制御・計測はロックで重複を防ぎます。既存スクリプトを直接起動したプロセスはロックの対象外です。
`control` を動かしたまま `frr_dscp_te.sh` / `frr_measure.sh` / `run_all_scenarios.sh` を直接実行すると、設定の上書きが起こり得ます。3クラスと同時に動かす場合は `run` を使ってください。

## 6. 設定と制御則

設定の元は [lab_config_c2.sh](../scripts/lab_config_c2.sh) です。ラッパーが別の設定ファイルを持つことはありません。

| 項目 | 既定値 |
|---|---|
| 無線CR1の初期整形帯域 | 2160M |
| 有線CR2 / CR3の整形帯域 | 各9G |
| 各クラスの送信 | 64ストリーム × 125000K = 8G |
| UDPデータグラム | 7000 B |
| 静的WCMP | 6:25:25 |
| 動的WCMP | `round(CR1の整形Mbps / 9000 × 100):100:100` (CR1重み1〜255) |
| 推定実効容量 | `min(PHY1, PHY2) × 0.52` |
| 動的整形目標 | 推定容量 × 0.9、整数Mbps、下限100 Mbps |
| 更新条件 | 現在値から10%を超える低下は即時、上昇は3回連続確認 |
| QoS | 小さい最低保証 + AF41優先、AF42/AF43は残余を2:1で競合 |

ラッパーの既定モードは `wcmp` です。既存 `lab_config_c2.sh` 自体の `primary` 既定や、`lab_config.sh` の `veth` 既定は維持しています。
コントローラは有線9G・SP有効・WRR 4:2:1を固定値で使うため、`run` / `control` はそれと矛盾する環境変数を拒否します。
環境変数を使う既存の静的比較も可能です。容量を変える場合はWCMPの比も合わせます。

```bash
sudo env CR1_BW=900M WCMP_W1=1 WCMP_W2=10 WCMP_W3=10 \
  bash scripts/radwin_experiment.sh measure 60 all wireless_900m_01 wcmp
```

送信量が容量を超えるのは実験の前提です。帯域の指定には整数M/G表記を使用してください。

## 7. 保存先と確認するファイル

```text
results/frr/radwin/dynamic/<タグ>/  # run / control。measureはradwin/comparison/<タグ>/
  settings.env          使用したC2設定・計測条件
  source_sha256.txt     関連スクリプトのハッシュ
  run.info              操作名・開始時刻
  commands.log          呼び出したコマンド
  console.log           実行画面の記録
  status.txt            終了コード・終了時刻
  validation.txt        計測の欠測/制御適用失敗チェック (run / measure)
  controller.csv        制御の観測値・目標値・適用値 (run / control)
  controller.log        コントローラの出力 (run。controlではconsole.log)
  controller.failed     コントローラが早期終了した場合のみ (run)
  frr_normal/           normalの既存計測ファイル
  frr_failure/          failureの既存計測ファイル (実施時)
  frr_failure_reroute/  failure_rerouteの既存計測ファイル (実施時)
  ja/                   既存plot_frr.pyが生成する日本語グラフ
```

`PRIO_HI=1` の静的計測では既存仕様どおりシナリオフォルダに `_priouniform` が付きます。

既存結果の分類と移動前後の対応は [結果一覧](../results/frr/README.md) を参照してください。
`frr_measure.sh` / `run_all_scenarios.sh` を直接実行した場合の既定保存先は `results/frr/incoming/<タグ>/` です。
`FRR_RESULTS_ROOT` を指定すれば保存先の親ディレクトリを変更できます。ラッパーは操作に応じてこの変数を設定し、呼び出す計測処理へ引き継ぎます。

- `throughput.csv`: 各Rxの毎秒受信量 (bytes/s)。Gbpsへの換算は `×8÷10^9`。
- `path_stats.csv`: LER_IngressからCR1/2/3への毎秒送信量 (bytes/s)。
- `iperf3_af*.log`: UDP受信、損失、ストリーム確立状況。
- `owd_af*.log`: クラスごとの片方向遅延。
- `tc_drops.csv` / `ip_drops.csv`: キュー・IP経路側のドロップ。
- `controller.csv`: UNIX時刻、各ホップPHY/MCS/dBm、推定/目標/適用Mbps、CR1重み、動作。

`validation.txt` のOKは、所定ストリームの確立・受信集計の存在・制御ログの存在と適用失敗の有無の検査です。
実験仮説の成立、損失ゼロ、グラフ生成成功まで意味しません。`status.txt` の終了コードと合わせて確認してください。
制御CSVは絶対時刻、既存の計測CSVは各モニター開始からの相対秒です。開始時刻を同じと仮定して重ね合わせないでください。

`plot_dynamic_control.py` は過去の単独プローブ用です。`--tput` と実際の時刻差 `--offset` が必要で、手動劣化を含むデータを想定しています。今回の `run` は既存の `plot_frr.py` によるグラフを生成します。

## 8. 保持している既存の制約

- 動的制御とTEモニターは `/run/radwin/weights.env` で重みを共有します (2026-09-25)。
  TEモニターは TS が30秒以内なら採用し、古い・無い・壊れている場合は固定の重み (WCMP_W1..3) に戻ります。
  W1=0 は「無線断のため CR1 を外す」の意味です。
- TEモニターは各経路の入口側 (LER_Ingress─CRn) と出口側 (CRn─LER_Egress) の両方の OSPF 隣接を見ます。
  無線 (CR1─LER_Egress) の断は BFD (300ms×3) により約1〜3秒で検知して CR1 を外します。
- `frr_dscp_te.sh` は `htb default 13`、障害注入側は `1:3` がdefaultであることを想定しており、記述が一致していません。また、既存pfifo葉へのnetem追加が成功しているかは実機のqdiscで確認が必要です。障害注入の成否はOSPF・tcの実状態とログで評価してください。今回の整理では障害注入方式を変更していません。
- MCS由来の容量推定は回復過渡時に遅れる場合があります。既存報告では27秒の遅れが記録されています。
- `--interval 2` は目標周期です。SSHに時間がかかれば実周期も延びます。
- `/tmp` の旧CSVは永続保存ではありません。新しい入口は実験フォルダへ直接記録します。

過去の [導入計画](radwin_integration_plan.md) と [9月18日の報告](進捗報告_動的制御_20260918.pdf) は、その時点の記録として残しています。
