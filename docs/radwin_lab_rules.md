# RADWIN 無線実験の共通ルール

`.claude/skills/` の実験用スキル (lab-bringup / radwin-link-check / radwin-characterize /
traffic-experiment / experiment-analysis) が共通で前提にする決まりと、過去につまずいた点。
スキルを使う前に一度読むこと。

## 構成の要点

- 送信 Tx1〜3 → LER_Ingress → CR1 / CR2 / CR3 → LER_Egress → 受信 Rx1〜3。全コンテナは PC (virttrx) 上の Docker。
- CR1 の区間は 60 GHz 無線 2 ホップ: `.31 )))無線1((( .32 ─中継─ .33 )))無線2((( .34`。CR2 / CR3 は有線。
- ODU (無線機) は RADWIN TerraNet V90 ×4、レンズ 37 dBi (ビーム幅 4°)。管理 IP は 192.168.1.31〜.34。
- 設定値・IP・QoS 設計は `CLAUDE.md` を正とする。ここには手順上の決まりだけを書く。

## 必ず守ること

| 決まり | 理由 |
|---|---|
| 起動・計測は `LAB_MODE=c2` で行う (`radwin_experiment.sh` は内部で固定) | 付け忘れると veth 用の設定 (全経路 9G) になり、無線経路で HTB が効かない。エラーは出ない |
| 計測中は無線の経路に人を入れない | 60 GHz は人体でほぼ遮られ、10 dB 以上落ち込む |
| 計測中は ODU の Web UI を閉じる。閉じてから 2 分待って始める | Web UI 使用中は ODU の応答が遅くなる (読み取り 1 回 3 秒 → 6〜21 秒) |
| ユーザーが打つコマンドは 1 行ずつ貼る。スペースは半角 | 改行で分断されたり (`head -1` が分かれる)、全角スペースで引数がファイル名になった事故がある |
| SONiC スイッチで `apt update/install` をしない | OS が壊れる |
| ODU のパスワードはスクリプトに書かない。`~/.radwin_pass` (chmod 600) に置く | 秘密情報の漏えい防止 |

## 結果の保存

- 保存先: 動的制御・同時計測は `results/frr/radwin/dynamic/`、無線の確認・特性測定は `results/frr/radwin/validation/`。
- フォルダ名: `YYYYMMDD_結果_目的_条件_連番`。結果は `running` (実行中・中断) / `success` / `fail`。
  `radwin_experiment.sh` は自動で付け替える。手作業で作ったフォルダ (validation) は、終わったら手で `running` を付け替える。
- `success` は「計測として正常に完了した」の意味で、実験仮説の成立は意味しない。

## 既知の現象とつまずき (原因が分かっているもの)

| 症状 | 原因 | 対処 |
|---|---|---|
| 送信は通るのに受信だけ 0 (iperf3 の接続が 0/64) | libvirt の VM (macvtap) が実験用 NIC の受信を奪う | `sudo bash scripts/check_nic_hijack.sh` で検出し、表示された VM を停止 |
| 無線の MCS が上がらない・不安定 | 通信がないと MCS は上がりきらない | 負荷をかけて測る (`radwin_live_monitor.py` は既定で負荷をかける) |
| 受信電力が約 8 dB 上下する 2 つの値を行き来する (Lock ON でも起きる) | 無線機がビームを電気的に切り替えている (片方向だけ変わる)。きっかけは未解明 | 判定で見つける (`sweep_point.sh` の判定)。逆向きの受信電力はほぼ変わらない |
| backoff を 20 にしても 6 と同じ | Web UI の backoff の上限は 6 (スライダーの最大)。範囲外は 6 に切り詰められる | 0〜6 だけを使う。1 段 ≈ 1 dB、効くのは設定した ODU の送信だけ |
| 帯域制限の検証で整形されない | `htb default 13` は存在しないクラス。fwmark なしの通信 (live_monitor の負荷、OSPF、BFD) は整形を通らない | 整形の検証は本番の計測 (fwmark 付き) で行う |
| ODU のドライバのパラメータ (PRS_MAX_MCS など) を書いても効かない | 起動時にしか読まれない | 使わない |
| 無線の実効上限が約 2.4 Gbps | 無線ではなく ODU の 2.5GbE ポート (実効 約 2475 Mbps) が律速。無線そのものは MCS12 で約 2624 Mbps | 仕様として扱う |
| `plot_frr.py` の自動生成図の値がおかしい (WCMP のとき) | 単一経路前提で、値をリンク容量で頭打ちにして描く | WCMP の評価は `results/frr/tools/` の解析スクリプトを使う |
