# frr-docker-lab-main2 CLAUDE.md

## 実験目的（不変の前提）

**この実験の目的は以下の2点。変更不可。**

1. **輻輳下での優先度ルーティング**
   リンク容量を超えた送信レートの環境で、DiffServ-TE（HTB SP+WRR）によりAF41（高）・AF42（中）・AF43（低）の優先度順に帯域を保証することを実証する。

2. **障害・キャパ低下時の自動リルーティング**
   リンク障害を自動検出し、OSPF-SR（FRR 8.4）によって動的に迂回経路へ切り替えることを実証する。

**送信レートがリンク容量を超えることは意図的設計。送信レートの変更を提案しないこと。**

### 3シナリオ比較が最終成果物

| シナリオ | 内容 |
|---|---|
| `normal` | 全3リンクECMP + WRR優先制御。障害なし |
| `failure` | t=20s に CR1 をダウン、t=40s 復旧。ECMP未更新のため損失継続 |
| `failure_reroute` | failure と同条件だが OSPF-SR が収束後に自動迂回 |

---

## ネットワークトポロジー

### 論理構成

```
Tx1 ─[AF41 UDP:1000]─┐
Tx2 ─[AF42 UDP:2000]─┤    ┌─CR1─┐    ┌─Rx1(AF41)
Tx3 ─[AF43 UDP:3000]─┴─[LER_Ingress]─┼─CR2─┤─[LER_Egress]─┼─Rx2(AF42)
                                       └─CR3─┘    └─Rx3(AF43)
```

各コンテナはDockerで動作。Linuxカーネルの MPLS + OSPF-SR（FRR 8.4）を使用。

### IPアドレス

| リンク | LER_Ingress側 | 対向側 |
|---|---|---|
| LER_Ingress ↔ Tx1 | leri-tx1: 10.0.1.1/30 | tx1-ler: 10.0.1.2/30 |
| LER_Ingress ↔ Tx2 | leri-tx2: 10.0.2.1/30 | tx2-ler: 10.0.2.2/30 |
| LER_Ingress ↔ Tx3 | leri-tx3: 10.0.3.1/30 | tx3-ler: 10.0.3.2/30 |
| LER_Ingress ↔ CR1 | leri-cr1: 10.1.3.1/30 | cr1-leri: 10.1.3.2/30 |
| LER_Ingress ↔ CR2 | leri-cr2: 10.1.4.1/30 | cr2-leri: 10.1.4.2/30 |
| LER_Ingress ↔ CR3 | leri-cr3: 10.1.5.1/30 | cr3-leri: 10.1.5.2/30 |
| CR1 ↔ LER_Egress | cr1-lere: 10.2.10.2/30 | lere-cr1: 10.2.10.1/30 |
| CR2 ↔ LER_Egress | cr2-lere: 10.2.11.2/30 | lere-cr2: 10.2.11.1/30 |
| CR3 ↔ LER_Egress | cr3-lere: 10.2.12.2/30 | lere-cr3: 10.2.12.1/30 |
| LER_Egress ↔ Rx1 | lere-rx1: 10.2.1.1/30 | rx1-lere: 10.2.1.2/30 |
| LER_Egress ↔ Rx2 | lere-rx2: 10.2.2.1/30 | rx2-lere: 10.2.2.2/30 |
| LER_Egress ↔ Rx3 | lere-rx3: 10.2.3.1/30 | rx3-lere: 10.2.3.2/30 |

ループバックIP（OSPF-SR Node SID用）:
- LER_Ingress: 192.168.0.1/32、SID index 1 → label 16001
- CR1: 192.168.0.2/32、SID index 2 → label 16002
- CR2: 192.168.0.3/32、SID index 3 → label 16003
- CR3: 192.168.0.4/32、SID index 4 → label 16004
- LER_Egress: 192.168.0.5/32、SID index 5 → label 16005

### 物理2SW構成（physical2_* スクリプト使用時）

VETHは不使用。2台のSONiCスイッチを物理ケーブルで接続。

| スイッチ | SSH接続先 | 収容コンテナ |
|---|---|---|
| SW1 | kannolab@192.168.128.33 | Tx1-3, LER_Ingress, CR1-3 |
| SW2 | kannolab@192.168.128.1 | LER_Egress, Rx1-3 |

**物理ケーブル接続:**

SW1内ループバック（コンテナ間接続）:
- Eth0↔Eth1: Tx1 ↔ LER_Ingress
- Eth2↔Eth3: Tx2 ↔ LER_Ingress
- Eth4↔Eth5: Tx3 ↔ LER_Ingress
- Eth6↔Eth7: LER_Ingress ↔ CR1
- Eth8↔Eth9: LER_Ingress ↔ CR2
- Eth10↔Eth11: LER_Ingress ↔ CR3

SW2内ループバック:
- Eth3↔Eth4: LER_Egress ↔ Rx1（VLAN20/21）
- Eth5↔Eth6: LER_Egress ↔ Rx2（VLAN22/23）
- Eth7↔Eth8: LER_Egress ↔ Rx3（VLAN24/25）

クロスSWリンク（1本のみ）:
- **SW1:Eth14 → SW2:Eth2**（VLAN44共有ブリッジ br-xsw）
- CR1/CR2/CR3の出口はSW1:Eth14の共有ブリッジ経由でSW2:Eth2に到達

---

## トラフィッククラスとQoS設計

### トラフィッククラス

| クラス | UDPポート | DSCP | fwmark | 宛先 | 優先度 |
|---|---|---|---|---|---|
| AF41 | 1000 | 34 (AF41) | 41 | Rx1 (10.2.1.2) | 高（SP） |
| AF42 | 2000 | 36 (AF42) | 42 | Rx2 (10.2.2.2) | 中（WRR 2） |
| AF43 | 3000 | 38 (AF43) | 43 | Rx3 (10.2.3.2) | 低（WRR 1） |

### HTB スケジューリング（SP + WRR）

AF41はStrict Priority（prio 0）、AF42/AF43はWRR比2:1（prio 1）。
netemによる人工遅延なし。輻輳時の自然なキュー待ち時間差でクラス差別化。

```
各CRリンク（100M）のHTB構成:
1:0  root  rate=100M
 ├── 1:1  AF41  prio=0  rate=4/7×100M  ceil=100M  (SP優先)
 ├── 1:2  AF42  prio=1  rate=2/7×100M  ceil=100M  (WRR 2)
 └── 1:3  AF43  prio=1  rate=1/7×100M  ceil=100M  (WRR 1)
```

### 送信レート設定（lab_config.sh）

```
TX1_RATE=60M    # AF41: CRリンク100M の60% → SP優先で全量通過
TX2_RATE=200M   # AF42: 輻輳させる（200M >> 2/7×100M≈28.5M）
TX3_RATE=200M   # AF43: 輻輳させる（200M >> 1/7×100M≈14.3M）
CR1_BW=CR2_BW=CR3_BW=100M
```

**期待する計測結果（normal シナリオ）:**
- AF41: ≈60 Mbps（送信量がSP保証帯域内に収まるため全量通過）
- AF42: ≈28.5 Mbps（残余帯域 40M を WRR 2:1 で分配）
- AF43: ≈14.3 Mbps（同上）

---

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

計測はPCから実行。SW1/SW2をSSH経由で制御。

```bash
# 全シナリオ計測（60秒 × 3シナリオ）
bash scripts/physical2_frr_measure_all.sh 60 all <タグ>

# 単一シナリオ
bash scripts/physical2_frr_measure_all.sh 60 normal <タグ>
```

| スクリプト | 場所 | 役割 |
|---|---|---|
| `physical2_frr_measure_all.sh` | PC | マスタースクリプト。スクリプトデプロイ・時刻同期・TC/HTB適用・各シナリオ実行・結果収集・グラフ生成 |
| `physical2_frr_measure_sw1.sh` | SW1 | iperf3クライアント起動、path_stats.csv・htb_class_stats.csv記録 |
| `physical2_frr_measure_sw2.sh` | SW2 | iperf3サーバ起動、throughput.csv・OWDログ記録 |
| `frr_dscp_te.sh` | SW1→デプロイ | TC/HTB/iptables設定。毎回計測前に再適用 |

**結果格納先:** `results/frr/<タグ>/frr_<scenario>/`

| ファイル | 内容 |
|---|---|
| `throughput.csv` | Rx1-3 の毎秒受信スループット (bytes/s) |
| `path_stats.csv` | leri-cr1 TX bps / cr1-leri RX bps / drops（毎秒） |
| `htb_class_stats.csv` | leri-cr1 の AF41/AF42/AF43 HTBクラス送信bps |
| `owd_af4{1,2,3}.log` | One-Way Delay（OWDプローブ） |

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

---

## 実験・作業方針

### 実験手順
veth（仮想環境）で動作を確認してから、実際の物理配線で実験を行うこと。
仮想環境で再現できない問題や性能計測の最終確認のみ物理環境で行う。

### フォルダ命名規則
新規フォルダは必要な場合のみ作成し、むやみに増やさないこと。
作成する場合は **日付と結果（成功/失敗）** が名前から判断できるようにすること。

```
命名例:
  20260629_success_normal_wrr/     # 成功
  20260629_fail_ospf_sr_label/     # 失敗
  20260630_success_physical2_all/  # 成功（物理2SW環境）
```
