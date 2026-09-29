---
name: lab-bringup
description: RADWIN 無線実験のラボ (LAB_MODE=c2) を起動し、計測できる状態かを確認する。「ラボを起動して」「実験の準備」「実験できる状態か確認」と言われたとき、または PC の再起動後・コンテナ停止後に使う。無線区間の設置と接続の確認は radwin-link-check、計測そのものは traffic-experiment を使う。
argument-hint: (引数不要)
---

# ラボの起動と前提確認

PC (virttrx) 上の Docker で FRR ラボを起動し、無線経路 (CR1) を含む 3 経路の WCMP と QoS を設定して、
計測できる状態であることを確認する。作業前に `docs/radwin_lab_rules.md` を読むこと。

完了の条件: 手順 6 の `check` がすべて OK、手順 7 で te_monitor が 0 個、手順 8 で無線 2 区間がつながっている。

## 事前に一度だけ用意するもの

ODU (無線機) のパスワードファイル。スクリプトはここから読む (スクリプトに書かない)。sudo を付けずに作る。

```bash
printf '%s' '<ODUのパスワード>' > ~/.radwin_pass
chmod 600 ~/.radwin_pass
```

## 手順 (各コマンドは 1 行ずつ実行する)

**1. 実験用 NIC を奪う VM がないか確認する**
```bash
sudo bash scripts/check_nic_hijack.sh
```
`[NG]` が出たら、表示された `sudo virsh shutdown <VM名>` を実行してから、もう一度確認する。
(VM が動いたままだと、送信は通るのに受信だけ 0 になる。エラーは出ない)

**2. ラボを起動する** (数分かかる)
```bash
sudo env LAB_MODE=c2 bash scripts/frr_all_up.sh
```
`LAB_MODE=c2` を必ず付ける。付け忘れると veth 用の設定で起動する。

**3. 起動時に立ち上がった te_monitor を止める**
```bash
sudo pkill -f frr_te_monitor.sh
```
`frr_all_up.sh` は最後に te_monitor を「経路 1 本 (primary)」の前提で起動する。
このままだと WCMP (3 経路) の経路表を書き換えてしまう。必要な計測では traffic-experiment の手順で起動し直す。

**4. 設定の中身を確認する** (sudo 不要)
```bash
bash scripts/radwin_experiment.sh config
```
`LAB_MODE=c2 / ROUTE_MODE=wcmp`、`CR1_BW=2160M`、`CR2_BW=9G`、`CR3_BW=9G`、各クラス 64 フロー であること。

**5. WCMP と QoS を設定する**
```bash
sudo bash scripts/radwin_experiment.sh prepare
```
6 本のリンクに `SP+WRR(4:2:1)` が表示され、`モード: wcmp — 3経路マルチパス 重み CR1:CR2:CR3 = 6:25:25` と出ること。
(`sch_htb: quantum of class 10000 is big` の Warning は無害)

**6. 計測の前提を確認する**
```bash
sudo bash scripts/radwin_experiment.sh check
```
4 項目 (LER_Ingress と CR1 の HTB、table 41 の nexthop 3 本、`fib_multipath_hash_policy = 1`) がすべて `[OK]` であること。

**7. te_monitor が残っていないことを確認する**
```bash
sudo bash scripts/check_weight_sharing.sh
```
`実行中の te_monitor: 0 個` であること。

**8. 無線がつながっていることを確認する**
```bash
sudo python3 scripts/radwin_telemetry.py
```
無線1・無線2 の両方に PHY レートと MCS が表示され、「未接続」がないこと。
未接続なら radwin-link-check で無線区間を確認する。

## うまくいかないとき

| 症状 | 確認すること |
|---|---|
| 手順 6 で nexthop が 3 本未満 | 手順 3 を飛ばして te_monitor が経路を書き換えた可能性。手順 3 → 5 → 6 をやり直す |
| 手順 6 で HTB がない | 手順 5 が失敗している。出力の `[NG]` を読む |
| 手順 8 で SSH のパスワードを聞かれる・失敗する | `~/.radwin_pass` の有無と中身。ODU の電源とケーブル |
| 起動後に受信が 0 | 手順 1 の VM を確認 (起動後に VM が立ち上がることがある) |

停止するとき: `sudo bash scripts/frr_down.sh`
