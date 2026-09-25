# RADWIN 無線チェーン統合計画

最終更新: 2026-09-07（LLDP・VLAN・カウンタの実測に基づく）

CR1 経路（CR1 ↔ LER_Egress）を 60GHz 無線 2 ホップに置き換えるための計画。
本書の「実測」項目はすべて SW1/SW2 から読み取った実データであり、推測ではない。

---

## 1. 無線チェーンの構成

```
SW1:Ethernet24 ─光─ KeepLINK-A ─[.31] )))無線1((( [.32]─中継─[.33] )))無線2((( [.34]─ KeepLINK-C ─光─ SW2:Ethernet18
```

| ODU | MAC | 管理IP | 役割 | SSID | ch | FW |
|---|---|---|---|---|---|---|
| ODU-A | `c4:93:00:57:16:e9` | 192.168.1.31 | PtP AP | radwin-link1 | 1 | r54664 |
| ODU-B | `c4:93:00:57:7c:70` | 192.168.1.32 | PtP Station | radwin-link1 | — | r54664 |
| ODU-C | `c4:93:00:60:35:df` | 192.168.1.33 | PtP AP | radwin-link2 | 4 | r54667 |
| ODU-D | `c4:93:00:60:35:e2` | 192.168.1.34 | PtP Station | radwin-link2 | — | r54667 |

機種はいずれも `RW-6P02-J260`（JPN 版・技適 R 006-0013B4）。

**ループしない理由**: ODU-A/ODU-B は別セグメント、ODU-C/ODU-D も別セグメント。
ODU-B と ODU-C は中継セグメントを共有するが無線の相手が異なるため、全体が一直線になる。

---

## 2. 物理接続マップ（LLDP 実測）

### SW1 — 192.168.128.33 / Accton AS7326-56X

| ポート | エイリアス | 対向 |
|---|---|---|
| Ethernet0 | Eth6/3(Port1) | SW2:Ethernet0 |
| Ethernet8 | Eth7/2(Port9) | SW1:Ethernet9（自機ループバック） |
| Ethernet9 | Eth11/2(Port10) | SW1:Ethernet8 |
| Ethernet10 | Eth11/1(Port11) | SW1:Ethernet11（自機ループバック） |
| Ethernet11 | Eth11/3(Port12) | SW1:Ethernet10 |
| Ethernet17 | Eth18/1(Port18) | SW2:Ethernet10 |
| **Ethernet18** | Eth19/1(Port19) | **PC `enp5s0f1`**（`98:b7:85:21:50:a9`）= CR1 側 |
| Ethernet20 | Eth19/2(Port21) | SW2:Ethernet12 |
| **Ethernet24** | Eth30/3(Port25) | **ODU-A**（無線チェーン入口） |

### SW2 — 192.168.128.1 / Accton AS7326-56X

| ポート | エイリアス | 対向 |
|---|---|---|
| Ethernet0 | Eth6/3(Port1) | SW1:Ethernet0 |
| Ethernet10 | Eth11/1(Port11) | SW1:Ethernet17 |
| **Ethernet11** | Eth11/3(Port12) | **PC `enp5s0f0`**（`98:b7:85:21:50:a8`）= LER_Egress 側 |
| Ethernet12 | Eth18/3(Port13) | SW1:Ethernet20 |
| **Ethernet18** | Eth19/1(Port19) | **ODU-D**（無線チェーン出口） |

SW1↔SW2 の直結は 3 本: `Eth0↔Eth0` / `Eth17↔Eth10` / `Eth20↔Eth12`。
無線チェーン用の VLAN にこれらを**絶対に含めないこと**（含めるとループしてブロードキャストストームになる）。

トランシーバは無線側 2 ポートとも OEM `SFP-10G-SR`（光・LC）で 10G リンクアップ。

---

## 3. VLAN の現状（実測）

| スイッチ | VLAN | メンバ | 種別 |
|---|---|---|---|
| SW1 | 10 | Ethernet0, Ethernet2 | untagged |
| SW1 | 11 | Ethernet4, **Ethernet18** | untagged |
| SW1 | 12 | Ethernet20, Ethernet22 | untagged |
| SW1 | 101 / 102 / 103 | Ethernet14, Ethernet17 | tagged |
| SW2 | 101 / 102 / 103 | Ethernet2, Ethernet10 | tagged |

### ここから判明したこと

- **コード中のコメントが言う VLAN 201/202/203 は running config に存在しない**
  （`scripts/frr_setup.sh:147` と `scripts/lab_config_c2.sh` の記述）。設定がドリフトしている。
- **SW1:Ethernet18（PC `enp5s0f1`）は VLAN 11 でリンクダウン中の Ethernet4 と組**になっており、
  SW2 側へ抜ける道がない。
- **SW2:Ethernet11（PC `enp5s0f0`）は `routed` で VLAN 未所属**。受信を全破棄している。
- SW2 は全ポートで `RX_DRP = RX_OK`。現在スイッチ経由のデータ経路は成立していない。
- PC の 10G NIC 6 本はすべて root namespace に IP を持つ（コンテナ未起動・ラボ未構築）。

**結論**: C2 経路 1 のスイッチ側の道は現時点で存在しない。
したがって無線導入は「既存の直結経路を外す」のではなく**新規に道を作る**作業になる。
ループのリスクが下がるので好都合。

---

## 4. VLAN 設定案（未実行）

既存で 10/11/12/101/102/103 が使用中のため、**VLAN 211** を新設する。

### SW1（192.168.128.33）

```bash
sudo config vlan add 211
sudo config vlan member del 11 Ethernet18      # 既存 VLAN 11 から外す
sudo config vlan member add -u 211 Ethernet18  # PC enp5s0f1（CR1 側）
sudo config vlan member add -u 211 Ethernet24  # 無線チェーン入口
sudo config save -y
```

### SW2（192.168.128.1）

```bash
sudo config vlan add 211
sudo config vlan member add -u 211 Ethernet18  # 無線チェーン出口
sudo config vlan member add -u 211 Ethernet11  # PC enp5s0f0（LER_Egress 側）
sudo config save -y
```

### 確認

```bash
show vlan brief
show interfaces status | grep -E "Ethernet11|Ethernet18|Ethernet24"
```

`Vlan` 列が `routed` から VLAN 所属に変われば、ASIC が破棄しなくなる。

### KNET VLAN pop は不要と考えられる

CLAUDE.md の KNET 制約（`tc ingress` での VLAN pop 必須）は、SONiC 自身がフレームを
Linux 側で終端する場合の話。C2 モードは物理 NIC をコンテナ netns へ移すため、
経路は「PC NIC → ケーブル → SW ポート → ASIC → SW ポート → ケーブル → PC NIC」で
SONiC の CPU/KNET を経由しない。**ただし実測で確認すること。**

---

## 5. 残作業と確認事項

### 実験前に必ず確認（優先度順）

1. **無線チェーンの疎通** — KeepLINK-A 側の PC で検証スクリプトを実行
   - Linux: `bash scripts/radwin_verify.sh <NIC名>`
   - Windows: PowerShell を管理者として実行し `.\scripts\radwin_verify.ps1 -Adapter "<アダプタ名>"`
2. **実効スループット** — 同スクリプトの iperf3 パート。`CR_BW` の根拠になる
3. **通過 MTU** — 同スクリプトが二分探索する。7900 未満なら OSPF の MTU 照合対策が必要
4. **中継部のポート速度** — 1G だと無線（約2Gbps）より先に銅が律速し、実験の前提が崩れる

### 設定変更が必要な箇所

| ファイル | 変更内容 | 状態 |
|---|---|---|
| `scripts/lab_config_c2.sh` | `CR1_BW` を **2100M** に（CR2/CR3 は有線のまま 9G） | **完了 2026-09-08** |
| `scripts/frr_setup.sh` | `wire_fabric_c2` に MTU 引数を追加し、CR1 のみ **7800** を渡す | **完了 2026-09-08** |
| `scripts/frr_dscp_te.sh` | `rate_to_kbps` を小数対応に修正（下記の注意参照） | **完了 2026-09-08** |
| SW1 / SW2 | 上記 VLAN 211 の設定 | 未着手（SONiC 到達不可） |

### 注意: rate_to_kbps の小数バグ

`scripts/` 配下の 10 ファイルに `rate_to_kbps()` の実装があり、そのうち多くが
`${r//[^0-9]/}` で非数字を全除去している。この実装は **`2.1G` を `21G` と誤解釈**し、
`total_kbps` が 10 倍になって HTB の保証帯域（`r_hi`/`r_me`/`r_lo`）が壊れる。

対策として **設定値は必ず整数の M 表記を使う**こと（`2.1G` ではなく `2100M`）。
`frr_dscp_te.sh` の実装のみ小数対応に修正済み。他の 9 ファイルは未修正:
`60_rsvp_te.sh` / `physical2_frr_ospfsr_sw1.sh` / `rsvp_monitor.sh` / `rsvp_monitor_v2.sh` /
`virttrx_tc.sh` / `physical2_frr_measure_sw1.sh` / `30_tc.sh` / `30_tc_sonic.sh` /
`physical2_docker_sw1.sh`

### 適用後の HTB 構成（検証済み）

| 経路 | 容量 | AF41 保証 | 借用プール |
|---|---|---|---|
| **CR1（無線）** | 2100 Mbps | 210 Mbps (10%) | 1800 Mbps (85.7%) |
| CR2（有線） | 9 Gbps | 900 Mbps (10%) | 7714 Mbps (85.7%) |
| CR3（有線） | 9 Gbps | 900 Mbps (10%) | 7714 Mbps (85.7%) |

保証 10% / 借用プール 85.7% の比率が 3 経路とも同一で、SP 実証の設計則を満たしている。

送信レート（`TX1_RATE` 〜 `TX3_RATE`）は変更しない。CLAUDE.md の設計原則どおり、
リンク容量を超過させたまま `CR_BW` だけ下げることで輻輳はむしろ強まる。

### 実験上の含意

| 項目 | 影響 |
|---|---|
| スループット | 2 ホップの最小値が上限。中継の store-and-forward でさらに低下 |
| OWD | 約 2 倍。TDD フレーム遅延が 2 回分乗る。グラフの縦軸レンジ見直しが必要 |
| 障害検出 | 無線が落ちても銅リンクは UP のまま。OSPF hello 1 / dead 3 + BFD で検出（設定済み） |
| 障害注入 | SSH 経由の "Kick client" で t=20s/40s を精度よく再現できる。物理 LOS 遮蔽は別途 |

`normal` シナリオでは 3 クラスとも CR1 が唯一の実働経路（`scripts/frr_dscp_te.sh:138-148`）
なので、**トラフィックは 100% 無線を通る**。CR2/CR3 は障害時の迂回先として必要。

---

## 6. 既知の未解決・未確認

- **無線 2 ホップが疎通するか未確認**（最重要）。LLDP は予約マルチキャストのためブリッジを
  越えず、無線の疎通判定には使えない。IP での ping が必要。
- ODU-A（.31）と ODU-D（.34）は `Antenna Kit` が `+TNPTP37DBI`（37dBi レンズ）設定。
  実物と一致しているか要確認。37dBi はビーム幅 4°×4°、遠方界の開始は 3〜9m。
  室内近距離ではレンズを外して `Base unit only` にするのが確実。
- ODU 間で FW が異なる（r54664 と r54667）。揃えるのが望ましい。
- KeepLINK の型番・ポート速度・PoE バジェット・ジャンボ対応が未確認。
