---
name: radwin-characterize
description: RADWIN 60GHz 無線区間の特性を測る。TX power backoff の設定値と実際の受信電力の低下の関係、無線区間の容量 (スループットの上限) とその律速箇所を調べる。「backoff の効き目を測りたい」「無線の容量を測って」「無線の最大スループットは」と言われたときに使う。接続・安定性の確認だけなら radwin-link-check、3クラスの計測は traffic-experiment を使う。
argument-hint: [backoff | capacity]
---

# 無線区間の特性測定

作業前に `docs/radwin_lab_rules.md` を読むこと。ラボ起動済み (lab-bringup)、無線が安定 (radwin-link-check の判定 OK) であること。
2 つの測定がある。依頼に合う方を行う。

## A. backoff と受信電力の低下の関係

**目的**: Web UI の TX power backoff を変えたとき、受信電力が実際に何 dB 下がるかを確かめる。
backoff は「最大出力から何 dB 下げるか」(単位は dB)。

**2026-09-25 に確認済みの結果** (3 m の設置で測定)
- Web UI のスライダーの上限は 6。数値欄に 20 を入れても 6 と同じ効き方になる (切り詰められる)。0〜6 だけを使う。
- 効くのは、設定した ODU の**送信**だけ。相手側の受信電力だけが下がる (.31 に設定 → .32 の受信電力が下がる)。
- 6 で約 6 dB 下がる。1 段あたり約 1 dB。リンクは切れない。
- 変更の反映に時間がかかる可能性がある (未確定)。設定後 3 分待ってから測る。

**手順**
1. 記録先を作る (日付と連番は実際の値に):
   ```bash
   mkdir -p results/frr/radwin/validation/20260929_running_backoff_01
   ```
2. 別のターミナルで負荷をかけたままにする: `sudo python3 scripts/radwin_live_monitor.py`
3. .31 の Web UI で backoff を 0 にして保存 → **Web UI を閉じて 3 分待つ** → 記録する:
   ```bash
   sudo bash scripts/sweep_point.sh bo0 30
   ```
4. backoff を 1, 2, …, 6 に変えながら、手順 3 と同じく記録する (ラベルは `bo1` … `bo6`)。
5. 判定が `乱れあり` の点は、同じラベルで測り直す。

**読み方**: `sweep.csv` の .32 の受信電力を、`bo0` との差にする。ゆっくりした変化を差し引くため、
.31 の受信電力 (backoff の影響を受けない向き) の変化を引いた値も見る。1 回ごとの値は `sweep_samples.csv` にある。

## B. 無線区間の容量と律速箇所

**目的**: 無線区間でどこまで流せるか、何が上限を決めているかを知る。3 種類の値を区別する。

| 値 | 測り方 | 2026-09-24 の実測 (3 m、MCS 12) |
|---|---|---|
| 無線そのものの能力 | Web UI の SpeedTest (下記) | TX 2624 Mbps / RX 2383 Mbps |
| 同上 (独立の確認) | ODU 内蔵の推定ツールの `currentThroughput` (下記) | 2623 Mbps (12 回平均) |
| ラボの経路での実測 | `radwin_live_monitor.py` の無線の受信量 | 約 2420 Mbps |

**結論 (律速箇所)**: 2420 < 2475 < 2624 Mbps。経路の上限は ODU の 2.5GbE ポート (実効 約 2475 Mbps) で、無線ではない。
無線の効率は 2624 / 4620 (MCS 12 の PHY レート) = 0.568。動的制御の容量推定 (PHY × 0.52) はこれより保守側。

**SpeedTest**: 親機 (.31) の Web UI で、接続中の子機の TX / RX SpeedTest の横にある「Run」を押す
(User Manual 4.2.4)。ODU 同士で測るので、Ethernet ポートの制約を受けない。

**推定ツール** (条件 A〜D をそれぞれ `--repeat` 回実行する。負荷をかける条件を含む):
```bash
sudo python3 scripts/radwin_estimator_trial.py --repeat 3
```
信用できるのは `currentThroughput` だけ。`mainMcs` と `estimatedThroughput` は実際の値と合わない (2026-09-24 に確認)。

**ラボの経路での実測** (Ctrl+C で終了。CSV に毎秒の値が残る):
```bash
sudo python3 scripts/radwin_live_monitor.py --telemetry 2 --log-csv results/frr/radwin/validation/20260929_running_capacity_01/live.csv
```
この負荷は fwmark を持たないので HTB の整形を通らない。無線経路の素の実力を測る用途に使う。
長いコマンドは 1 行のまま貼ること (記録先のフォルダは先に `mkdir -p` で作っておく)。

## 注意

- 容量は MCS で大きく変わる。通信がないと MCS が上がらないので、必ず負荷をかけて測る。
- ODU ドライバのパラメータ (PRS_MAX_MCS など) の書き換えや、TDD の比率の変更は効かない (起動時のみ読まれる / 自動のみ)。容量を人為的に変える手段には使えない。
