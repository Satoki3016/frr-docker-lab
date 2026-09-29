---
name: traffic-experiment
description: 3クラス (AF41/AF42/AF43) の通信を流しながら、無線容量に追従する動的制御 (WCMP の重みと HTB) を動かす計測と、無線が切れたときに CR1 が経路から外れるかの検証を行う。「計測して」「動的制御の実験」「無線断の検証」「ケーブルを抜く試験」と言われたときに使う。準備は lab-bringup と radwin-link-check、結果の図は experiment-analysis を使う。
argument-hint: [run | linkdown]
---

# 通信を流す計測と、無線断の検証

作業前に `docs/radwin_lab_rules.md` を読むこと。ラボ起動済み (lab-bringup)、無線が安定 (radwin-link-check の判定 OK) であること。
2 つの実験がある。依頼に合う方を行う。

## 仕組みの要点 (結果を読むのに必要)

- 動的制御 `radwin_wcmp_controller.py` が 2 秒ごとに ODU の MCS を読み、無線の容量を推定して
  CR1 の HTB の整形レートと WCMP の重み (CR1:CR2:CR3 = w1:100:100) を決める。
  下げは即座、上げは 3 回続けて確認してから。±10% 未満の変化は無視する。
- 経路表 (LER_Ingress の table 41〜43) を書くのは 1 か所だけ。te_monitor が動いていれば te_monitor が書き、
  制御は重みを `/run/radwin/weights.env` で渡す。te_monitor が止まっていれば制御が自分で書く。
- 無線が切れたとき: te_monitor は OSPF 隣接 (BFD、約 0.9 秒で検知) を見て約 1〜3 秒で CR1 を外す。
  制御は「未接続」を 2 回続けて読むと重み 0 で CR1 を外す (約 14 秒)。戻すのは両方が回復を確認してから。

## A. 動的制御と 3 クラスの同時計測 (run)

**目的**: 無線の容量が変わっても、最優先の AF41 が途切れないかを確かめる。

1. 計測を始める (計測秒 120、目的語 `antenna` の例。保存名は自動で付く):
   ```bash
   sudo bash scripts/radwin_experiment.sh run 120 antenna 2
   ```
   冒頭に `保存名: 2026…_running_antenna_wcmp_01` のように表示される。
2. 計測中に無線の容量を変える操作をする場合は、別のターミナルで操作のたびに時刻を控える:
   ```bash
   date +%T
   ```
   (2026-09-18 の実施では、計測中にアンテナの向きを手で変えて容量を下げ、元に戻した)
3. 終了すると `validation.txt` が作られ、保存名の `running` が `success` か `fail` に変わる。

**合格の条件** (`validation.txt`): 3 クラスとも `64/64 streams / OK`、`controller: … 0 apply failures / OK`。
`NG` なら終了コード 1 で、フォルダ名は `fail` になる。

**注意**: このシナリオ (normal) では te_monitor は止まっている。無線が切れたときに CR1 を外すのは制御だけ (約 14 秒)。

**参考** (2026-09-18、`results/frr/radwin/dynamic/20260918_success_dynamic_integrated`):
無線の容量が約 4.4 分の 1 に落ちても AF41 は 8.0 Gbps を維持し、180 秒間で断ゼロ。

## B. 無線断の検証 (linkdown)

**目的**: 無線が本当に切れたとき、CR1 が数秒で経路から外れ、戻ったときに制御の重みで戻るかを確かめる。
ターミナルを 3 つ使う。

1. 事前に BFD の断の回数を控える (無線側 `peer 10.0.2.2` の `Session down events`):
   ```bash
   sudo docker exec frr-CR1 vtysh -c "show bfd peers counters"
   ```
2. ターミナル A: te_monitor を WCMP で起動する (開いたままにする)
   ```bash
   sudo env LAB_MODE=c2 ROUTE_MODE=wcmp bash scripts/frr_te_monitor.sh /tmp/frr_te_monitor.log
   ```
3. ターミナル C: 状態を 1 秒ごとに表示する。`実行中の te_monitor: 1 個` を確認する
   ```bash
   sudo watch -n1 bash scripts/check_weight_sharing.sh
   ```
4. ターミナル B: 制御を起動する。`init … (経路=te_monitor)` と出ること
   ```bash
   sudo bash scripts/radwin_experiment.sh control "" 2
   ```
   ターミナル C の table 41 に `leri-cr1=<重み>` が入っていること。
5. **.32 (無線1 の子機) の LAN ケーブルを抜く。** .31 側は抜かない
   (.31 を抜くと管理用の通信ごと切れ、無線の断ではなく有線の断の試験になる)。
6. 1 分ほど待ってからケーブルを挿し直す。挿し直したあと、ODU の起動と無線の再接続を待つ
   (2026-09-25 は、抜いてから再接続まで約 1.5 分)。
7. 終了: ターミナル B → A → C の順に Ctrl+C。続けて BFD の回数を確認し、te_monitor の記録を保存する
   (`<結果フォルダ>` はターミナル B の最後の `結果:` の行に表示されたパス):
   ```bash
   sudo docker exec frr-CR1 vtysh -c "show bfd peers counters"
   ```
   ```bash
   sudo cp /tmp/frr_te_monitor.log <結果フォルダ>/te_monitor.log
   ```

**期待される動き** (2026-09-25 の実測、`results/frr/radwin/dynamic/20260925_success_control_wcmp_03`)
| 時点 | 出来事 |
|---|---|
| 抜いてから約 1〜3 秒 | te_monitor のログ `OSPF隣接消失検知: 出口側 (CR─LER_Egress)` → table 41 から leri-cr1 が消える |
| 約 14 秒 | 制御が `link_lost(1/2)` → `link_down` (重み 0) |
| 無線の再接続 (抜いてから約 1.5 分) | OSPF が回復しても、制御が 3 回確認するまで CR1 は外したまま |
| その直後 | 制御が `link_up` → 小さい重み (例 5) で CR1 を戻し、MCS の回復に合わせて段階的に上げる |
| 終了後 | BFD の無線側 `Session down events` が 1 増える |

## 計測中の監視 (どちらの実験でも使える)

| 見たいもの | コマンド |
|---|---|
| 無線区間のスループット・MCS・受信電力 | `sudo python3 scripts/radwin_live_monitor.py --telemetry 2` (本番の計測中は負荷をかけず表示だけ) |
| 重み・経路表・te_monitor の状態 | `sudo watch -n1 bash scripts/check_weight_sharing.sh` |
| te_monitor の経路更新の記録 | `tail -f /tmp/frr_te_monitor.log` |

## うまくいかないとき

| 症状 | 確認すること |
|---|---|
| `validation.txt` で AF4x が `0/64 streams` | VM が NIC を奪っている (`check_nic_hijack.sh`) |
| 制御が `[NG] … HTB qdisc がない` などで止まる | lab-bringup の手順 5・6 をやり直す |
| B で制御が `(経路=self)` と出る | te_monitor が動いていない。ターミナル A を確認 |
| B で CR1 が外れない | ターミナル A のログに `出口側` の検知が出ているか。BFD が動いているか (`show bfd peers brief`) |
| フォルダ名が `running` のまま残った | 計測が強制終了された。結果は使わない |
