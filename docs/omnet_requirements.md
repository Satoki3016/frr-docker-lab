# OMNeT++ 実装要件書
## Docker ラボ構成の OMNeT++ 移植

---

## 1. ネットワークトポロジー

### 1.1 ノード構成

| ノード名 | 役割 | 種別 |
|----------|------|------|
| Tx1, Tx2, Tx3 | トラフィック送信ホスト | ホスト |
| Rx1, Rx2, Rx3 | トラフィック受信ホスト | ホスト |
| LER_Ingress | 入口ラベルエッジルーター | MPLS LER |
| LER_Egress | 出口ラベルエッジルーター | MPLS LER |
| CoreRouter1 | コアルーター (CR1) | MPLS LSR |
| CoreRouter2 | コアルーター (CR2) | MPLS LSR |
| CoreRouter3 | コアルーター (CR3) | MPLS LSR |

合計: 11ノード (ホスト6, ルーター5)

### 1.2 リンク構成とIPアドレス

```
Tx1 (10.0.1.2) ──────── LER_Ingress (10.0.1.1)
Tx2 (10.0.2.2) ──────── LER_Ingress (10.0.2.1)
Tx3 (10.0.3.2) ──────── LER_Ingress (10.0.3.1)

LER_Ingress (10.1.3.1) ── CR1 (10.1.3.2)   ← AF41 Primary (10Mbps/2ms×2)
LER_Ingress (10.1.4.1) ── CR2 (10.1.4.2)   ← AF42 Primary (5Mbps/5ms×2)
LER_Ingress (10.1.5.1) ── CR3 (10.1.5.2)   ← AF43 Primary (1Mbps/10ms×2)

CR1 (10.2.10.2) ──────── LER_Egress (10.2.10.1)
CR2 (10.2.11.2) ──────── LER_Egress (10.2.11.1)
CR3 (10.2.12.2) ──────── LER_Egress (10.2.12.1)

LER_Egress (10.2.1.1) ── Rx1 (10.2.1.2)
LER_Egress (10.2.2.1) ── Rx2 (10.2.2.2)
LER_Egress (10.2.3.1) ── Rx3 (10.2.3.2)
```

合計: 12リンク (veth ペア)

---

## 2. トラフィッククラスと DiffServ

### 2.1 クラス定義

| クラス | DSCP 値 | TOS バイト | 優先度 | 宛先ポート | 宛先ホスト |
|--------|---------|-----------|--------|-----------|-----------|
| AF41 | 34 (0x22) | 0x88 | 高 | UDP 1000 | Rx1 (10.2.1.2) |
| AF42 | 36 (0x24) | 0x90 | 中 | UDP 2000 | Rx2 (10.2.2.2) |
| AF43 | 38 (0x26) | 0x98 | 低 | UDP 3000 | Rx3 (10.2.3.2) |

### 2.2 DSCP マーキング

LER_Ingress の PREROUTING で宛先ポートに応じて DSCP を付与する。

```
UDP dport 1000 → DSCP AF41
UDP dport 2000 → DSCP AF42
UDP dport 3000 → DSCP AF43
```

### 2.3 ポリシールーティング (RSVP-TE シナリオ)

DSCP 値に応じて fwmark を付与し、独立したルーティングテーブルで転送先を決定する。

```
DSCP AF41 → fwmark 41 → routing table 41
DSCP AF42 → fwmark 42 → routing table 42
DSCP AF43 → fwmark 43 → routing table 43
```

---

## 3. QoS: HTB + WRR スケジューリング

### 3.1 設計方針 (パターン A: 高優先 = 高帯域・低遅延)

優先度が高いクラスほど大きな帯域と小さな遅延のリンクを使用する。

### 3.2 LER_Ingress 送出リンクの帯域・遅延設定

| リンク | 合計帯域 | AF41 帯域 | AF42 帯域 | AF43 帯域 | netem 遅延 |
|--------|---------|---------|---------|---------|-----------|
| leri-cr1 | 10 Mbps | 5714 kbps | 2857 kbps | 1428 kbps | 2 ms |
| leri-cr2 |  5 Mbps | 2857 kbps | 1428 kbps |  714 kbps | 5 ms |
| leri-cr3 |  1 Mbps |  571 kbps |  285 kbps |  142 kbps | 10 ms |

WRR 重み比 = 4:2:1 (quantum = weight × 1400 bytes)

### 3.3 CoreRouter 送出リンクの帯域・遅延設定

| リンク | 合計帯域 | AF41 帯域 | AF42 帯域 | AF43 帯域 | netem 遅延 |
|--------|---------|---------|---------|---------|-----------|
| cr1-lere | 10 Mbps | 5714 kbps | 2857 kbps | 1428 kbps | 2 ms |
| cr2-lere |  5 Mbps | 2857 kbps | 1428 kbps |  714 kbps | 5 ms |
| cr3-lere |  1 Mbps |  571 kbps |  285 kbps |  142 kbps | 10 ms |

### 3.4 LER_Egress 送出リンク

| リンク | キュー種別 | キュー長 |
|--------|----------|---------|
| lere-rx1 | DropTail (pfifo) | 100 パケット |
| lere-rx2 | DropTail (pfifo) | 100 パケット |
| lere-rx3 | DropTail (pfifo) | 100 パケット |

帯域制限なし (LER_Egress → Rx はボトルネックにならない設計)

### 3.5 期待スループット (正常時)

全クラスが 11.2 Mbps で送信を試みた場合:
- Rx1 (AF41): 約 8 Mbps 受信
- Rx2 (AF42): 約 4 Mbps 受信
- Rx3 (AF43): 約 0.9 Mbps 受信

### 3.6 期待 RTT (正常時, ping)

| クラス | 経路 | 片道遅延 (netem×2ホップ) | 期待 RTT |
|--------|------|------------------------|---------|
| AF41 | CR1 | 2ms + 2ms = 4ms | 約 4 ms |
| AF42 | CR2 | 5ms + 5ms = 10ms | 約 10 ms |
| AF43 | CR3 | 10ms + 10ms = 20ms | 約 20 ms |

(戻りパスに tc/netem なし → RTT ≒ 片道遅延)

---

## 4. MPLS 静的 LSP 設定

### 4.1 Primary LSP

| トンネル | クラス | Push ラベル | 経路 | Swap | Pop | 宛先 |
|---------|--------|------------|------|------|-----|------|
| Tunnel 1 | AF41 | 100 | CR1 | 100→101 | 101 | Rx1 |
| Tunnel 2 | AF42 | 200 | CR2 | 200→201 | 201 | Rx2 |
| Tunnel 3 | AF43 | 300 | CR3 | 300→301 | 301 | Rx3 |

### 4.2 Backup LSP (RSVP-TE シナリオ用)

| トンネル | クラス | Push ラベル | 経路 | Swap | Pop | 宛先 |
|---------|--------|------------|------|------|-----|------|
| AF41 Backup | AF41 | 110 | CR2 | 110→111 | 111 | Rx1 |
| AF42 Backup | AF42 | 210 | CR3 | 210→211 | 211 | Rx2 |

### 4.3 LER_Ingress の FEC → LSP マッピング (Primary)

```
main table / table 41:  10.2.1.2/32 → encap mpls 100 via CR1
main table / table 42:  10.2.2.2/32 → encap mpls 200 via CR2
main table / table 43:  10.2.3.2/32 → encap mpls 300 via CR3
```

---

## 5. RSVP-TE 動的パス切替

### 5.1 設計概要

実際の RSVP-TE シグナリングの代わりに、受信スループット監視による
動的ルート書き換えで RSVP-TE の PathErr/Reroute 動作を模擬する。

### 5.2 AF42 障害検知・切替 (主要機能)

| パラメータ | 値 | 説明 |
|-----------|-----|------|
| 監視対象 | Rx2 受信レート | rx2-lere インターフェース rx_bytes |
| 障害検知閾値 | 200 Kbps | これ未満で障害とみなす |
| 復旧検知閾値 | 1 Mbps | これ超で正常復旧とみなす |
| 監視間隔 | 1 秒 | |
| ウォームアップ | 5 秒 | 起動直後の誤検知防止 |

**障害検知時の動作:**
```
table 42:  10.2.2.2/32 → encap mpls 210 via CR3 (Backup LSP)
main table: 10.2.2.2/32 → encap mpls 210 via CR3 (Backup LSP)
```

**復旧時の動作:**
```
table 42:  10.2.2.2/32 → encap mpls 200 via CR2 (Primary LSP)
main table: 10.2.2.2/32 → encap mpls 200 via CR2 (Primary LSP)
```

### 5.3 AF41 輻輳検知・切替 (補助機能)

| パラメータ | 値 | 説明 |
|-----------|-----|------|
| 監視対象 | LER_Ingress の leri-cr1 HTB バックログ | classid 1:1 |
| 輻輳検知閾値 | 40,000 bytes (40 KB) | これ超で輻輳とみなす |
| 復旧検知閾値 | 10,000 bytes (10 KB) | これ未満で復旧とみなす |

**輻輳検知時:** table 41 の Rx1 宛を label 110 via CR2 (Backup) に切替
**復旧時:** table 41 の Rx1 宛を label 100 via CR1 (Primary) に戻す

---

## 6. 障害シナリオ

### 6.1 シナリオ一覧

| シナリオ名 | 内容 |
|-----------|------|
| normal | 障害なし (60 秒計測) |
| failure | t=20s に cr2-lere リンクダウン、t=40s 復旧 (RSVP-TE なし) |
| failure_rsvp | t=20s に cr2-lere リンクダウン、t=40s 復旧 + RSVP-TE 動的切替あり |

### 6.2 障害注入の詳細

- **障害箇所**: CoreRouter2 の cr2-lere インターフェース (CR2 → LER_Egress 間)
- **障害種別**: リンクダウン (ip link set cr2-lere down)
- **影響クラス**: AF42 (Primary が CR2 経由のため)
- **AF41・AF43 への影響**: なし (それぞれ CR1・CR3 経由)

### 6.3 RSVP-TE シナリオでの期待動作

| 時刻 | イベント | AF42 経路 | 帯域 | RTT |
|------|---------|-----------|------|-----|
| 0〜20s | 正常 | CR2 Primary (label 200) | 約 4 Mbps | 約 10 ms |
| 20s | cr2-lere ダウン | — (パケットロス) | 0 | — |
| 20〜21s | RSVP-TE 検知・切替 | CR3 Backup (label 210) | 約 1 Mbps | 約 20 ms |
| 21〜40s | Backup 経路で転送継続 | CR3 Backup | 約 1 Mbps | 約 20 ms |
| 40s | cr2-lere 復旧 | — |— | — |
| 40〜41s | RSVP-TE 復旧検知 | CR2 Primary (label 200) | 約 4 Mbps | 約 10 ms |
| 41〜60s | 正常復帰 | CR2 Primary | 約 4 Mbps | 約 10 ms |

---

## 7. トラフィック生成条件

### 7.1 iperf3 UDP (スループット計測)

| 項目 | 設定値 |
|------|-------|
| プロトコル | UDP |
| 送信レート | 11.2 Mbps (各クラス) |
| パケット長 | 1400 bytes |
| 計測時間 | 60 秒 |
| ポート | Tx1→1000, Tx2→2000, Tx3→3000 |
| 計測方法 | サーバ側 JSON (受信量ベース) |

### 7.2 ping (RTT 計測)

| 項目 | 設定値 |
|------|-------|
| 間隔 | 0.1 秒 (10 pps) |
| 計測時間 | 60 秒 |
| 宛先 | Tx1→10.2.1.2, Tx2→10.2.2.2, Tx3→10.2.3.2 |

---

## 8. OMNeT++ 実装における対応関係

| Docker 機能 | OMNeT++ / INET モジュール |
|------------|--------------------------|
| veth リンク | `DatarateChannel` (datarate, delay パラメータ) |
| HTB クラス帯域制限 | `DatarateChannel.datarate` |
| netem 遅延 | `DatarateChannel.delay` |
| WRR スケジューリング | `DiffservQueue` / `WrrScheduler` |
| DropTail キュー | `DropTailQueue` |
| iptables DSCP マーキング | `DscpMarker` |
| ip rule + fwmark | `MultiFieldClassifier` + `LabelForwardingTable` |
| MPLS push/swap/pop | `LibTable` (Static MPLS forwarding) |
| RSVP-TE 動的切替 | `RsvpTe` または `ScriptableMplsRouter` でルート書き換え |
| iperf3 UDP | `UdpBasicApp` (送信) + `UdpSink` (受信) |
| ping | `PingApp` |
| リンク障害注入 | `ScenarioManager` (`at t=20s: set-channel-param delay INF` 等) |

---

## 9. 静的ルーティングテーブル (IP フォワーディング)

### LER_Ingress

| 宛先 | ゲートウェイ | メトリック | 備考 |
|------|------------|---------|------|
| 10.2.1.0/24 | 10.1.3.2 (CR1) | 1 | Rx1 Primary |
| 10.2.1.0/24 | 10.1.4.2 (CR2) | 2 | Rx1 Secondary |
| 10.2.1.0/24 | 10.1.5.2 (CR3) | 3 | Rx1 Tertiary |
| 10.2.2.0/24 | 10.1.4.2 (CR2) | 1 | Rx2 Primary |
| 10.2.2.0/24 | 10.1.5.2 (CR3) | 2 | Rx2 Secondary |
| 10.2.2.0/24 | 10.1.3.2 (CR1) | 3 | Rx2 Tertiary |
| 10.2.3.0/24 | 10.1.5.2 (CR3) | 1 | Rx3 Primary |
| 10.2.3.0/24 | 10.1.4.2 (CR2) | 2 | Rx3 Secondary |
| 10.2.3.0/24 | 10.1.3.2 (CR1) | 3 | Rx3 Tertiary |

(MPLS 有効時は encap mpls で上書きされるため、IP ルートは ICMP/制御用)

### CoreRouter1

| 宛先 | ゲートウェイ |
|------|------------|
| 10.0.{1,2,3}.0/24 | 10.1.3.1 (LER_Ingress) |
| 10.2.{1,2,3}.0/24 | 10.2.10.1 (LER_Egress) |

### CoreRouter2

| 宛先 | ゲートウェイ |
|------|------------|
| 10.0.{1,2,3}.0/24 | 10.1.4.1 (LER_Ingress) |
| 10.2.{1,2,3}.0/24 | 10.2.11.1 (LER_Egress) |

### CoreRouter3

| 宛先 | ゲートウェイ |
|------|------------|
| 10.0.{1,2,3}.0/24 | 10.1.5.1 (LER_Ingress) |
| 10.2.{1,2,3}.0/24 | 10.2.12.1 (LER_Egress) |
