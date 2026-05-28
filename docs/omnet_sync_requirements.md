# OMNeT++ 設定同期要件書
## Docker ラボ現設定 → OMNeT++ への反映

作成日: 2026-04-14

---

## 1. 現状の差分サマリー

| 項目 | Docker (現設定) | OMNeT++ (現設定) | 対応要否 |
|------|----------------|-----------------|---------|
| リンク帯域・遅延 | CR1=10M/2ms, CR2=5M/5ms, CR3=1M/10ms | 同一 ✓ | 不要 |
| トラフィックレート | 11.2Mbps × 3クラス | 1ms間隔×1400B = 11.2Mbps ✓ | 不要 |
| WRR重み | 4:2:1 | 4:2:1 ✓ | 不要 |
| 計測時間 | 0〜60s | startTime=1s, stopTime=59s | **要修正** |
| 障害時刻 | t=20s/t=40s | t=20s/t=40s ✓ | 不要 |
| 障害注入方法 | ip link set down | delay=1000s | 機能的に等価（後述）|
| RSVP-TE検知 | スループット+リンク状態監視(1s) | Hello timeout(2s) | 検知遅延が異なる |
| failureシナリオ | RSVP-TEなし障害 | 未定義（常にRSVP-TE有効） | **要追加** |
| バックアップ経路 | AF42→CR3(label210) | Tunnel2 backup=lspid202? | **要確認** |

---

## 2. 変更が必要な箇所

### 2-1. アプリケーション開始・終了時刻の統一

**Docker**: iperf3クライアントは t=0s に送信開始、t=60s で終了  
**OMNeT++ 現状**: startTime=1s, stopTime=59s → 実効58秒

**MPLSDynamic.ini の変更箇所:**

```ini
# 変更前
**.Tx*.app[0].startTime = 1s
**.Tx*.app[0].stopTime  = 59s

# 変更後
**.Tx*.app[0].startTime = 0s
**.Tx*.app[0].stopTime  = 60s
```

---

### 2-2. 3シナリオの明示的な定義

Dockerには `normal` / `failure` / `failure_rsvp` の3シナリオがあるが、
OMNeT++には `normal` と RSVP-TE有効の障害シナリオしかない。
**「RSVP-TEなし障害シナリオ」が欠けている。**

**MPLSDynamic.ini に追加する Config:**

```ini
# ---- normal: 障害なし ----
[Config MPLSDynamic_Normal]
extends = MPLSDynamicBase
**.scenarioManager.script = xmldoc("MPLSDynamic_normal_scenario.xml")
description = "Normal scenario: no failures, baseline QoS measurement"

# ---- failure: 障害あり、RSVP-TE 無効 ----
[Config MPLSDynamic_Failure]
extends = MPLSDynamicBase
**.scenarioManager.script = xmldoc("MPLSDynamic_scenario.xml")
# RSVP-TE のパス切替を無効化 (障害をそのまま観測)
**.LER*.rsvp.typename      = "RsvpTe"       # 標準モジュール (自動切替なし)
**.CoreRouter*.rsvp.typename = "RsvpTe"
description = "Failure scenario: cr2-lere down at t=20s without RSVP-TE rerouting"

# ---- failure_rsvp: 障害あり、RSVP-TE 有効 ----
[Config MPLSDynamic_FailureRsvp]
extends = MPLSDynamicBase
**.scenarioManager.script = xmldoc("MPLSDynamic_scenario.xml")
# RsvpTeScriptableExtended はそのまま使用
description = "Failure + RSVP-TE rerouting: AF42 switches to CR3 backup after failure"
```

---

### 2-3. 障害注入方法の確認（delay=1000s の妥当性）

**Docker**: `ip link set cr2-lere down` → インターフェースが物理的にダウン  
**OMNeT++**: `set-channel-param delay=1000s` → パケットが1000秒遅延（事実上ロスト）

**機能的に等価である理由:**
- RSVP-TE Hello 間隔 = 0.5s、タイムアウト = 2s
- delay=1000s の場合、Hello パケットが sim-time-limit(60s)内に届かない
- → t=22s 頃に Hello timeout → RSVP-TE が隣接ノードのダウンを検知
- → Docker の動作（link down → ~2s後に検知）と一致

**ただし注意点:**  
t=40s に delay=5ms へ戻した時、それまでに送られた遅延パケットが
t=1020s+ に到着する（シミュレーション範囲外なので実質無視）。
復旧後の Hello は正常に届くため、復旧検知も問題なく動作する。

→ **変更不要**（現状の delay=1000s アプローチで問題なし）

---

### 2-4. バックアップ経路の確認

**Docker**: AF42障害時 → label 210 via CR3（LowSpeedLink: 1Mbps/10ms）

**OMNeT++ LER_Ingress_traffic.xml の Tunnel 2:**
```xml
<path><lspid>200</lspid> ... </path>  <!-- Primary: CR2 -->
<path><lspid>201</lspid> ... </path>  <!-- Backup 1: ??? -->
<path><lspid>202</lspid> ... </path>  <!-- Backup 2: ??? -->
```

**確認が必要:**  
lspid 201 / 202 がそれぞれ CR1経由 / CR3経由のどちらに対応するか、
CoreRouter1.rt / CoreRouter3.rt のラベルテーブルを確認する。

**期待する対応:**
| lspid | 経路 | Docker対応 |
|-------|------|-----------|
| 200 | CR2 (Primary) | label 200 |
| 201 | CR1 または CR3 | （未使用または label 110/210） |
| 202 | CR3 (Backup) | label 210 |

RSVP-TE が障害時に lspid 202（CR3経由）を選択することを確認すること。
選択ロジックは `RsvpTeScriptableExtended` のパス優先度設定による。

---

### 2-5. RSVP-TE 検知タイミングの対応付け

| 検知フェーズ | Docker | OMNeT++ |
|------------|--------|---------|
| 障害検知 | cr2-lere=down かつ rx2_rate<200Kbps → ~1s | Hello timeout 2s → t≈22s |
| バックアップ切替完了 | 即時（ip route replace） | restorationDelay=2s → t≈24s |
| 復旧検知 | cr2-lere=up → 即時 | Hello 再確立 → ~1s → t≈41s |
| Primary復旧完了 | 即時 | restorationDelay=2s → t≈43s |

**グラフ上での見え方の違い:**
- Docker: t=20sに急落、t≈21sに回復（~1s遅延）
- OMNeT++: t=20sに急落、t≈24sに回復（~4s遅延）

この違いは意図的な設計差として報告書に記載する。

---

## 3. 変更不要な項目（整合済み）

| 項目 | 値 | 確認 |
|------|-----|------|
| ネットワークトポロジー | 11ノード・12リンク | ✓ |
| HighSpeedLink | 10Mbps, delay=2ms | ✓ |
| MediumSpeedLink | 5Mbps, delay=5ms | ✓ |
| LowSpeedLink | 1Mbps, delay=10ms | ✓ |
| Tx1 送信レート | 1ms間隔×1400B=11.2Mbps | ✓ |
| Tx2 送信レート | 同上 | ✓ |
| Tx3 送信レート | 同上 | ✓ |
| DSCP マーキング | port→AF41/AF42/AF43 | ✓ |
| WRR重み | 4:2:1 | ✓ |
| 障害時刻 | t=20s down, t=40s up | ✓ |
| 計測時間 | 60s | △（startTime修正後に一致） |
| FEC設定 | 宛先IP→トンネルID | ✓ |

---

## 4. 実施優先順位

| 優先度 | 作業内容 | 対象ファイル |
|--------|---------|------------|
| 高 | アプリ startTime/stopTime を 0s/60s に変更 | MPLSDynamic.ini |
| 高 | 3シナリオ Config を明示的に定義 | MPLSDynamic.ini |
| 中 | lspid 201/202 の経路確認（CoreRouter.rt） | CoreRouter1.rt, CoreRouter3.rt |
| 中 | failure シナリオ（RSVP-TE 無効化）の動作確認 | MPLSDynamic.ini |
| 低 | 検知タイミング差異を報告書に記載 | — |
