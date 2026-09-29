# frr-docker-lab-main2 CLAUDE.md

## 実験目的（不変の前提）

**この実験の目的は以下の2点。変更不可。**

1. **輻輳下での優先度ルーティング**
   リンク容量を超えた送信レートの環境で、DiffServ-TE（HTB SP+WRR）によりAF41（高）・AF42（中）・AF43（低）の優先度順に帯域を保証することを実証する。

2. **障害・キャパ低下時の自動リルーティング**
   リンク障害・容量低下を自動検出し、OSPF-SR（FRR 8.4）の網の上で動的に迂回経路へ切り替えることを実証する。
   （役割分担: OSPF-SR はトポロジとラベルを提供し、障害は BFD＋OSPF 隣接で検知する。
   迂回と分配は te_monitor と動的制御がポリシー経路表 table 41〜43 を書き換えて行う。
   OSPF の最短経路計算が入口の経路を直接切り替えているわけではない）

**送信レートに関する設計原則（不変）:**
1. **リンクの帯域幅を超過する送信レートにすること**（輻輳を意図的に発生させる）
2. **最優先クラス（AF41）は輻輳下でも極力ロスを避けることを目標とする**（SP効果の実証）
3. **リアルに近い状況を目指す**

**送信レートがリンク容量を超えることは意図的設計。送信レートの変更を提案しないこと。**

### 3シナリオ比較が最終成果物

| シナリオ | 内容 |
|---|---|
| `normal` | 3経路 WCMP + SP/WRR 優先制御。障害なし |
| `failure` | t=20s に CR1 をダウン、t=40s 復旧。迂回なし（比較用） |
| `failure_reroute` | failure と同条件だが、OSPF 隣接の消失を te_monitor が検知して CR1 を経路表から外し自動迂回 |

**障害の与え方:** 障害は無線 ODU のケーブル抜去で与える（シナリオ `manual`：自動注入なし・te_monitor あり）。
`failure` / `failure_reroute` の自動注入（t=20〜40s に leri-cr1 へ netem）は無線区間を入れる前の代替手段で、
HTB の葉にだけ netem を付けるため OSPF hello と BFD（fwmark なし → direct queue）を止められず、迂回を再現しない可能性が高い（未検証・未修正）。

---

## ネットワークトポロジー（現行: LAB_MODE=c2 + RADWIN 無線）

### 論理構成

```
Tx1 ─[AF41 UDP:1000]─┐          ┌─CR1═══(60GHz 無線2ホップ)═══┐          ┌─Rx1(AF41)
Tx2 ─[AF42 UDP:2000]─┼─LER_Ingress┼─CR2────────(有線 10G)───────┼LER_Egress─┼─Rx2(AF42)
Tx3 ─[AF43 UDP:3000]─┘          └─CR3────────(有線 10G)───────┘          └─Rx3(AF43)
```

- 全コンテナは PC（virttrx）上の Docker。Linux カーネルの MPLS + OSPF-SR（FRR 8.4、`frr-<名前>` コンテナは本体と netns 共有）。
- Tx〜LER_Ingress〜CR は PC 内の veth。**CR→LER_Egress の3本だけが物理経路**（PC の専用 10G NIC ペア → SW1 ASIC → SW2 ASIC → PC）。
- **CR1 経路は RADWIN TerraNet V90 ×4 の 60GHz 2ホップ**（.31)))(.32─中継─.33)))(.34、ch1 / ch4、MTU 7800）。
  経路の実効上限は ODU の 2.5GbE ポート（約 2475 Mbps）。無線そのものは MCS12 で約 2624 Mbps。
- 起動・計測は必ず `LAB_MODE=c2`（`radwin_experiment.sh` は内部で固定）。

### IPアドレス（scripts/frr_setup.sh の配線定義）

| リンク | 手前側 | 奥側 |
|---|---|---|
| Tx1 ↔ LER_Ingress | tx1-leri: 10.10.1.1/30 | leri-tx1: 10.10.1.2/30 |
| Tx2 ↔ LER_Ingress | tx2-leri: 10.10.2.1/30 | leri-tx2: 10.10.2.2/30 |
| Tx3 ↔ LER_Ingress | tx3-leri: 10.10.3.1/30 | leri-tx3: 10.10.3.2/30 |
| LER_Ingress ↔ CR1 | leri-cr1: 10.0.1.1/30 | cr1-leri: 10.0.1.2/30 |
| LER_Ingress ↔ CR2 | leri-cr2: 10.0.3.1/30 | cr2-leri: 10.0.3.2/30 |
| LER_Ingress ↔ CR3 | leri-cr3: 10.0.5.1/30 | cr3-leri: 10.0.5.2/30 |
| CR1 ↔ LER_Egress（無線） | cr1-lere: 10.0.2.1/30 | lere-cr1: 10.0.2.2/30 |
| CR2 ↔ LER_Egress | cr2-lere: 10.0.4.1/30 | lere-cr2: 10.0.4.2/30 |
| CR3 ↔ LER_Egress | cr3-lere: 10.0.6.1/30 | lere-cr3: 10.0.6.2/30 |
| LER_Egress ↔ Rx1 | lere-rx1: 10.20.1.2/30 | rx1-lere: 10.20.1.1/30 |
| LER_Egress ↔ Rx2 | lere-rx2: 10.20.2.2/30 | rx2-lere: 10.20.2.1/30 |
| LER_Egress ↔ Rx3 | lere-rx3: 10.20.3.2/30 | rx3-lere: 10.20.3.1/30 |

ODU の管理 IP は 192.168.1.31〜.34。CR1 netns の cr1-lere に 192.168.1.200/24 を付けて SSH する（`radwin_ssh.py` が自動で付与）。

ループバックIP（OSPF-SR Node SID用）:
- LER_Ingress: 192.168.0.1/32、SID index 1 → label 16001
- CR1: 192.168.0.2/32、SID index 2 → label 16002
- CR2: 192.168.0.3/32、SID index 3 → label 16003
- CR3: 192.168.0.4/32、SID index 4 → label 16004
- LER_Egress: 192.168.0.5/32、SID index 5 → label 16005

旧構成（`physical2_*` スクリプト、SONiC 2台にコンテナを収容）は現在使っていない。

---

## トラフィッククラスとQoS設計

### トラフィッククラス

| クラス | UDPポート（iperf3 / OWD） | DSCP | fwmark | 宛先 | 優先度 |
|---|---|---|---|---|---|
| AF41 | 1000 / 5001 | 34 (AF41) | 41 | Rx1 (10.20.1.1) | 高（SP） |
| AF42 | 2000 / 5002 | 36 (AF42) | 42 | Rx2 (10.20.2.1) | 中（WRR 2） |
| AF43 | 3000 / 5003 | 38 (AF43) | 43 | Rx3 (10.20.3.1) | 低（WRR 1） |

### HTB スケジューリング（SP + WRR）

AF41はStrict Priority（prio 0）、AF42/AF43はWRR比2:1（prio 1）。
netemによる人工遅延なし。輻輳時の自然なキュー待ち時間差でクラス差別化。

```
各CRリンクのHTB構成（C = リンクの整形レート。CR2/CR3 は 9G、CR1 は 2160M が初期値で動的制御が更新）:
1:0  root  rate=C   default 13（存在しないクラス → fwmark なしの通信は整形を通らない）
 ├── 1:1  AF41  prio=0  rate=C/10              ceil=C  (SP優先)
 ├── 1:2  AF42  prio=1  rate=(2/7)×C/10        ceil=C  (WRR 2)
 └── 1:3  AF43  prio=1  rate=(1/7)×C/10        ceil=C  (WRR 1)
例 C=9G: 900M / 257M / 129M
```

**全クラスの保証rateを意図的に小さく（1/10）設定している。** HTBは保証帯域（GREEN）を
prioに関係なく先に全クラスへ配り、prio（SP）が効くのは借用（YELLOW）分配のみのため、
保証を縮小して帯域の約85%を借用プールに置く。借用分配は prio=0 のAF41が最優先（SP）、
残余を AF42/AF43 が quantum比 2:1（WRR）で分配する。
（保証rateをフルシェア 2/7・1/7 のままにすると保証合計が先に消費され、
AF41 が需要 8G に到達できない — 2026-07-03実測で確認済み）

HTBのquantumが AF41:AF42:AF43 = 4:2:1 のため、全クラスが輻輳する状況では帯域が 4:2:1 で分配される。

### 送信レートと経路の重み（scripts/lab_config_c2.sh）

iperf3 は1クラスあたり `-P 64 -b 125000K`（64フロー × 125 Mbps = 8G/クラス、合計 24G）。
フロー数が多いのは WCMP（フロー単位のハッシュ分配）で容量比を表現するため（128 は接続取りこぼしで不可）。

```
CR1_BW=2160M  CR2_BW=9G  CR3_BW=9G   # 合計 20.16G < 送信 24G（意図的な輻輳）
ROUTE_MODE=wcmp                      # 重み CR1:CR2:CR3 = 6:25:25（容量比。動的制御中は w1:100:100）
```

**期待値（normal、重みどおりにフローが分かれた場合の理論値）:**
各クラスの需要は CR1 に 8G×6/56≈0.857G、CR2/CR3 に各 8G×25/56≈3.571G。各リンクで AF41 が先に満たされ、残りを AF42:AF43=2:1 で分ける（AF42 は需要で頭打ち）。
- AF41: 8.0 Gbps（無損失）
- AF42: ≈8.0 Gbps
- AF43: ≈4.16 Gbps（残り全部）
- 実測（2026-09-18、`20260918_success_dynamic_integrated` の基準区間）: AF41 8.023 / AF42 7.524 / AF43 4.375 Gbps。AF42/AF43 と理論値の差の原因は未検証。

単一の 9G リンクに全クラスを流す場合（primary）の理論値: AF41 8.0 / AF42 ≈0.667 / AF43 ≈0.333 Gbps。

---

## 迂回・分配の仕組み（2026-09-25 時点の実装）

| 要素 | 役割 |
|---|---|
| OSPF-SR | Node SID（ラベル 16005 など）の配布と、CR の MPLS 転送表の構築。入口の経路選択には使っていない |
| BFD | 全 OSPF インタフェースで FRR 既定値（300ms×3 ≈ 0.9 秒）。OSPF 隣接を速く落とす |
| `frr_te_monitor.sh` | 各経路の入口側（LER_Ingress─CRn）と出口側（CRn─LER_Egress）の OSPF 隣接を監視し、落ちた経路を table 41〜43 から外す |
| `radwin_wcmp_controller.py` | 無線の MCS から容量を推定し、HTB と WCMP の重みを決める。重みは `/run/radwin/weights.env` で te_monitor に渡す。無線断（未接続2回連続）では重み 0 で CR1 を外す |
| MPLS | 3経路とも同じラベル 16005（「LER_Egress へ」）。経路は入口の送出インタフェースで決まる。優先度は MPLS TC ではなく内側 IP の DSCP で分類 |

## OSPF-SR（FRR 8.4）設定必須事項

FRR 8.4でOSPF-SRを有効化するには `capability opaque` が必須。なければNode SIDが配布されない。

```
router ospf
 capability opaque
 mpls-te on
 mpls-te router-address <loopback-ip>
 segment-routing on
 segment-routing global-block 16000 23999
 segment-routing node-msd 8
 segment-routing prefix <loopback-ip>/32 index <N>
```

診断: `show ip ospf` で `OpaqueCapability flag is disabled` が出ていれば根本原因確定。

---

## 計測スクリプト体系

計測は PC（virttrx）で `sudo` 実行する。入口は `scripts/radwin_experiment.sh`（`--plan` で実行内容だけ表示）。

```bash
sudo bash scripts/radwin_experiment.sh run 180 unplug 2 manual   # 計測 + 動的制御（障害はケーブル抜去）
sudo bash scripts/radwin_experiment.sh control "" 2              # 動的制御だけ（Ctrl+C で終了）
sudo bash scripts/radwin_experiment.sh measure 60 all "" wcmp    # 動的制御なしの 3シナリオ比較
```

| スクリプト | 役割 |
|---|---|
| `radwin_experiment.sh` | 入口。設定固定・保存名の付与・QoS 適用・計測・検査（validation.txt）・結果名の付け替え |
| `frr_measure.sh` | 1シナリオの計測（iperf3・OWD・経路と HTB の記録、te_monitor の起動） |
| `frr_dscp_te.sh` | iptables（DSCP・fwmark）・ポリシー経路・HTB の設定。計測前に毎回適用 |
| `frr_te_monitor.sh` | OSPF 隣接（入口側・出口側）を監視して経路表を更新 |
| `radwin_wcmp_controller.py` | 無線の MCS から容量を推定し HTB と重みを更新 |
| `check_weight_sharing.sh` | 重み・経路表・te_monitor の状態を1画面で表示（`sudo watch -n1 ...`） |

**結果格納先:** `results/frr/radwin/dynamic/<保存名>/`（run・control）、`results/frr/radwin/comparison/<保存名>/`（measure）

| ファイル | 内容 |
|---|---|
| `frr_<シナリオ>/throughput.csv` | Rx1-3 の毎秒受信スループット (bytes/s) |
| `frr_<シナリオ>/path_stats.csv` | 各 CR 経路の毎秒送信量 |
| `frr_<シナリオ>/timebase.txt` | 計測 t=0 の絶対時刻（controller.csv と重ねるのに使う） |
| `controller.csv` | 動的制御の観測値・推定容量・適用値・重み（絶対時刻） |
| `te_monitor.log` | 経路表の更新記録（manual / failure_reroute で自動保存） |
| `validation.txt` / `status.txt` | 欠測・制御失敗の検査 / 終了コードと合否 |

WCMP の結果の図は `results/frr/tools/`（`plot_integrated_run.py` など）で作る。`plot_frr.py` の自動生成図は単一経路前提で、WCMP では値がリンク容量で頭打ちになり正しくない。

---

## SONiC制約（ハードウェア起因）

- **`apt update/install` 絶対禁止。** SONiCのファイルシステムはイミュータブルでaptがOSを破壊する。ツール不足時はDockerコンテナ経由かバイナリコピーで対処。
- **BCM ASICはcpuをuntagged bitmap(ubm)に追加不可。** KNETがフレームをLinuxに渡す際に常にVLANタグが付く。物理EthernetX→Linuxブリッジ接続時は `tc ingress` でVLAN popが必須。
- **VLANサブインタフェース方式は不使用。** KNETのTXパスがVLANタグ付きフレームをASICに転送しないため送信方向が機能しない。

```bash
# tc ingress VLAN pop の例
tc qdisc add dev EthernetX handle ffff: ingress
tc filter add dev EthernetX parent ffff: protocol 802.1Q flower vlan_id <ID> action vlan pop
```

---

## 品質方針

時間がかかってもよいので最高品質で精査すること。速度より品質を優先。

### グラフ品質基準

**グラフを作成・修正する際の基準は「Q1ジャーナルの査読を通るかどうか」。**

- チャートタイプの選択・レイアウト・凡例・軸ラベル・フォントサイズ・色使いすべてにおいて、IEEE/ACMのトップカンファレンス・Q1ジャーナル論文として投稿できる品質を維持すること。
- **グラフ内で使用する数式・計算式もQ1ジャーナル水準であること。** 近似式・導出過程・単位変換に誤りや曖昧さがあれば指摘・修正すること。
- 「見やすい」「きれいに見える」は理由にならない。査読者が数値を正確に読み取れ、主張が図だけで伝わることが基準。
- 積み上げグラフは加算関係が成立するときのみ使用可。独立した量の比較には折れ線・棒グラフを用いること。

---

## 実験・作業方針

### 実験手順
veth（仮想環境）で動作を確認してから、実際の物理配線で実験を行うこと。
仮想環境で再現できない問題や性能計測の最終確認のみ物理環境で行う。

### フォルダ命名規則
新規フォルダは必要な場合のみ作成し、むやみに増やさないこと。
名前は **`YYYYMMDD_結果_目的_条件_連番`**（2026-09-25 統一）。日付・合否・内容の順に読める。

```
命名例:
  20260925_success_unplug_wcmp_01/   # 正常に完了
  20260925_fail_unplug_wcmp_02/      # 欠測・制御の失敗あり
  20260925_running_unplug_wcmp_03/   # 途中で強制終了（running のまま残った）
```

- 結果語（running / success / fail）は `radwin_experiment.sh` が自動で付け替える。手で付けない。
- success は「計測として正常に完了した」の意味で、実験仮説の成立は意味しない。
- 解析スクリプトには結果語を省いた名前（`20260925_unplug_wcmp_01`）でも渡せる。
- 2026-09-25 より前の結果語なしのフォルダは名前を変えずに残している。
