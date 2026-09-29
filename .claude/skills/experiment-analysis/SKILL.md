---
name: experiment-analysis
description: RADWIN 無線実験の結果フォルダを読み、合否を判定して図を作る。「結果を評価して」「図にして」「計測の結果を見て」と言われたとき、traffic-experiment・radwin-link-check・radwin-characterize の計測が終わったあとに使う。計測そのものは行わない。
argument-hint: [結果フォルダ名 (結果語を省いてもよい)]
---

# 実験結果の評価と作図

作業前に `docs/radwin_lab_rules.md` を読むこと。図の品質基準は `CLAUDE.md` の「グラフ品質基準」(Q1 ジャーナルの査読水準) に従う。

## 1. 結果フォルダを特定する

- 置き場所: `results/frr/radwin/dynamic/` (run・control)、`results/frr/radwin/validation/` (無線の確認・特性測定)。
- 解析スクリプトの `--dir` には、フォルダ名そのもの、または結果語を省いた名前 (`20260925_control_wcmp_03`) を渡せる。
- フォルダ名が `running` のまま → 計測が途中で止まった。評価に使わない。

## 2. まず合否を確かめる (図を作る前に)

| 実験 | 見るファイル | 合格 |
|---|---|---|
| run (3 クラス + 動的制御) | `validation.txt`、`status.txt` | 3 クラスとも `64/64 streams / OK`、`controller: … 0 apply failures / OK`、`result=success` |
| control (制御のみ・無線断の検証) | `controller.csv` の `action` 列、`te_monitor.log` | `_FAIL` を含む行がない。無線断の検証なら `link_down` と `link_up` がそろい、te_monitor に `出口側` の検知がある |
| 無線の確認・特性測定 | `sweep.csv` (各点の中央値)、`sweep_samples.csv` (1 回ごとの値) | 記録時に表示された `[判定]` が OK の点だけを使う。同じラベルが複数あれば最後の記録を使う |

`controller.csv` は絶対時刻 (UNIX 秒)、計測の CSV (`frr_*/throughput.csv` など) は計測開始からの相対秒。
両者を重ねるときは `frr_*/timebase.txt` の開始時刻を使う (スクリプトは自動で行う)。開始時刻が同じと仮定して重ねない。

## 3. 図を作る

| 実験 | コマンド | 出力 (結果フォルダ内) | 何が分かるか |
|---|---|---|---|
| run | `python3 results/frr/tools/plot_integrated_run.py --dir <フォルダ> --layout report` | `result_throughput.{pdf,png}` | (a) 無線区間の実測と制御の整形レート (b) 各クラスの受信スループット (c) 劣化前を 100% とした相対値 |
| run | 同上で `--layout power` | `result_signal_power.{pdf,png}` | 無線 2 区間の受信電力の時間変化 |
| run | 同上で `--layout full` (既定) | `integrated_run.{pdf,png}` | 上記に物理層 (MCS・PHY) を加えた詳細版 |
| control | `python3 results/frr/tools/plot_weight_sharing.py --dir <フォルダ>` | `result_weight_sharing.{pdf,png}` | 制御が決めた重みと、te_monitor が経路表に書いた重みの一致、反映の遅れ |
| control / run | `python3 results/frr/tools/plot_radio_timeseries.py --dir <フォルダ>` | `result_radio_timeseries.{pdf,png}` | MCS と受信電力の時間変化 (`live.csv` があればスループットも) |

- sudo は不要。フォルダに複数の `frr_*` がある run では `plot_integrated_run.py` に `--scenario <名前>` を付ける。
- `plot_weight_sharing.py` は `te_monitor.log` が必要 (traffic-experiment の手順 B-7 で保存する)。
- **`plot_frr.py` (計測後に自動で作られる `ja/` `en/` の図) は WCMP の結果に使わない。**
  単一経路前提で、値をリンク容量で頭打ちにして描くため、3 経路の結果では誤った図になる。

## 4. 数値で報告するときの決まり

- 区間 (劣化前・劣化中・回復後) ごとの平均や中央値を、図の読み取りではなく CSV から計算して示す。
- 受信電力は 1 dB 単位でしか読めず、Lock ON でも約 8 dB の状態の切り替わりが起きることがある。
  1 回の値ではなく中央値で比べる。切り替わりが疑われるときは、逆向き (.31 の受信電力) も並べて示す。
- 容量の推定値 (PHY × 0.52) は推定であり、スループットの実測ではないことを明記する。
- 図の中の式・単位は Q1 水準で書く。積み上げグラフは加算関係が成り立つときだけ使う。

## 5. 過去の結果 (比較の基準)

| 結果フォルダ | 内容 |
|---|---|
| `results/frr/radwin/dynamic/20260918_success_dynamic_integrated` | run: 無線容量が約 4.4 分の 1 に落ちても AF41 は 8.0 Gbps を維持、断ゼロ |
| `results/frr/radwin/dynamic/20260925_success_control_wcmp_03` | 無線断の検証: te_monitor が約 1〜3 秒で CR1 を外し、制御の重みで段階的に戻した |
| `results/frr/radwin/validation/20260928_running_anglesweep_hop1_01` | 15 m・Lock ON での安定性の確認 (check3 と 16:49 の check4 が判定 OK)。角度の測定を続けるため、名前は running のまま |
