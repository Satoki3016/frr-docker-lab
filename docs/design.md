# FRR Docker Lab 設計文書

## 1. ネットワークトポロジー

```
Tx1 ──────────────────────────────────────────────── Rx1
Tx2 ──[LER_Ingress]──[CR1/CR2/CR3]──[LER_Egress]─── Rx2
Tx3 ──────────────────────────────────────────────── Rx3
```

### ノード一覧

| ノード | 役割 |
|---|---|
| Tx1 / Tx2 / Tx3 | 送信ホスト (iperf3 UDP クライアント) |
| Rx1 / Rx2 / Rx3 | 受信ホスト (iperf3 UDP サーバー) |
| LER_Ingress | 入口 LER: DSCP マーキング・ポリシールーティング・MPLS push |
| CoreRouter1/2/3 | MPLS トランジット: ラベルスワップ |
| LER_Egress | 出口 LER: MPLS pop・IP 転送 |

### インターフェースとアドレス

```
Tx1(tx1-ler:10.0.1.2) ──── LER_Ingress(leri-tx1:10.0.1.1)
Tx2(tx2-ler:10.0.2.2) ──── LER_Ingress(leri-tx2:10.0.2.1)
Tx3(tx3-ler:10.0.3.2) ──── LER_Ingress(leri-tx3:10.0.3.1)

LER_Ingress(leri-cr1:10.1.3.1) ──── CoreRouter1(cr1-leri:10.1.3.2)
LER_Ingress(leri-cr2:10.1.4.1) ──── CoreRouter2(cr2-leri:10.1.4.2)
LER_Ingress(leri-cr3:10.1.5.1) ──── CoreRouter3(cr3-leri:10.1.5.2)

CoreRouter1(cr1-lere:10.2.10.2) ──── LER_Egress(lere-cr1:10.2.10.1)
CoreRouter2(cr2-lere:10.2.11.2) ──── LER_Egress(lere-cr2:10.2.11.1)
CoreRouter3(cr3-lere:10.2.12.2) ──── LER_Egress(lere-cr3:10.2.12.1)

LER_Egress(lere-rx1:10.2.1.1) ──── Rx1(rx1-lere:10.2.1.2)
LER_Egress(lere-rx2:10.2.2.1) ──── Rx2(rx2-lere:10.2.2.2)
LER_Egress(lere-rx3:10.2.3.1) ──── Rx3(rx3-lere:10.2.3.2)
```

### トラフィッククラス

| クラス | UDP 宛先ポート | DSCP | 優先度 | 宛先 |
|---|---|---|---|---|
| AF41 | 1000 | 34 (0x22) | 高 | Rx1 (10.2.1.2) |
| AF42 | 2000 | 36 (0x24) | 中 | Rx2 (10.2.2.2) |
| AF43 | 3000 | 38 (0x26) | 低 | Rx3 (10.2.3.2) |

---

## 2. ルーティング

### 2.1 IP ルーティング (静的)

`20_wire.sh` で設定。ノードごとに静的経路を追加する。

**LER_Ingress**: Rx 宛は複数メトリックで経路設定（通常ルーティングの fallback 用）。
実際の転送は後述のポリシールーティングが優先される。

**CoreRouter1/2/3**: Tx 宛および Rx 宛のデフォルト静的経路のみ。
MPLS 動作時は IP 転送より MPLS ラベル転送が先に処理される。

**LER_Egress**: Tx 宛は各 CoreRouter 経由の複数メトリック静的経路。

### 2.2 ポリシールーティング (LER_Ingress)

`60_rsvp_te.sh` で設定。DSCP → fwmark → ip rule → per-class ルーティングテーブルの順に処理する。

```
パケット受信 (leri-tx?)
    │
    ├─[iptables mangle PREROUTING]
    │   UDP dport 1000  → DSCP=AF41 → fwmark=41
    │   UDP dport 2000  → DSCP=AF42 → fwmark=42
    │   UDP dport 3000  → DSCP=AF43 → fwmark=43
    │   ICMP on leri-tx1 → DSCP=AF41 → fwmark=41
    │   ICMP on leri-tx2 → DSCP=AF42 → fwmark=42
    │   ICMP on leri-tx3 → DSCP=AF43 → fwmark=43
    │
    └─[ip rule]
        fwmark 41 → table 41 (AF41 ルーティングテーブル)
        fwmark 42 → table 42 (AF42 ルーティングテーブル)
        fwmark 43 → table 43 (AF43 ルーティングテーブル)
```

各ルーティングテーブルには ECMP nexthop が登録される（詳細は次章）。

---

## 3. MPLS-TE

### 3.1 設計概要

Linux カーネルの静的 MPLS (mpls_router / mpls_iptunnel) を用いて MPLS-TE を模擬する。
実際の RSVP シグナリングは行わず、MPLS ラベルと経路をスクリプトで静的に設定する。

各トラフィッククラスは LER_Ingress でラベルを push し、CoreRouter でスワップ、LER_Egress で pop する。
クラスごとに異なるラベルを割り当てることで、コアネットワーク内でもクラスを識別できる。

### 3.2 LSP (Label Switched Path) 一覧

全 9 パスを事前確立する。

| クラス | 経路 | push | transit (swap) | pop |
|---|---|---|---|---|
| AF41 | CR1 経由 | 100 | 100→101 (CR1) | 101→Rx1 |
| AF41 | CR2 経由 | 110 | 110→111 (CR2) | 111→Rx1 |
| AF41 | CR3 経由 | 120 | 120→121 (CR3) | 121→Rx1 |
| AF42 | CR1 経由 | 200 | 200→201 (CR1) | 201→Rx2 |
| AF42 | CR2 経由 | 200 | 200→201 (CR2) | 201→Rx2 |
| AF42 | CR3 経由 | 210 | 210→211 (CR3) | 211→Rx2 |
| AF43 | CR1 経由 | 300 | 300→301 (CR1) | 301→Rx3 |
| AF43 | CR2 経由 | 310 | 310→311 (CR2) | 311→Rx3 |
| AF43 | CR3 経由 | 300 | 300→301 (CR3) | 301→Rx3 |

### 3.3 ECMP による負荷分散

LER_Ingress の各クラス用ルーティングテーブルに 3 つの nexthop を登録し、ECMP で 3 CoreRouter に分散する。

```bash
# table 41 (AF41)
ip route replace table 41 10.2.1.2/32
    nexthop encap mpls 100 via 10.1.3.2 dev leri-cr1   # PRIMARY
    nexthop encap mpls 110 via 10.1.4.2 dev leri-cr2
    nexthop encap mpls 120 via 10.1.5.2 dev leri-cr3
```

ECMP ハッシュは L4 (src/dst IP + src/dst port) ベース (`fib_multipath_hash_policy=1`)。
3 並列ストリームを送信することで 3 経路に分散させる。

### 3.4 FRR (Fast Reroute) — failure_rsvp シナリオ

`rsvp_monitor.sh` が LER_Ingress の leri-cr1/2/3 の operstate を 1 秒間隔でポーリングする。

**障害検知時** (leri-cr1 ダウンを例とする):
```
[DOWN] CR1 (leri-cr1) ← AF41 指定プライマリ LSP 切断
       MPLS-TE FRR: AF41 を残存リンク(CR2+CR3)に迂回
→ table 41/42/43 を CR2+CR3 の nexthop のみで再構築
```

**復旧検知時**:
```
[UP] CR1 (leri-cr1) → AF41 PRIMARY LSP 復旧
→ table 41/42/43 に CR1 nexthop を再追加
```

AF41 の CR1 は「指定プライマリ」として扱い、CR1 障害時に MPLS-TE FRR ログを出力する。
経路再構築は全クラス共通で ECMP を再生成する。

**failure シナリオとの比較**:

| | failure | failure_rsvp |
|---|---|---|
| t=0-20s | AF41=171M, AF42=86M, AF43=43M | 同左 |
| t=20-40s (CR1ダウン) | AF41 が CR1 に送り続けて損失 | FRR で CR2+CR3 に迂回、114M 継続 |
| t=40-60s (CR1復旧) | AF41 復旧 (経路は再設定しない) | CR1 を ECMP に再追加 |

---

## 4. 優先度制御 (QoS)

### 4.1 設計概要

DiffServ モデルに基づき、LER_Ingress で DSCP マーキングを行い、
ネットワーク内では DSCP を参照して帯域と遅延を制御する。

優先度制御は 3 層構造で実装する:

```
[Layer 1] Ingress policing  (leri-tx1/2/3)
          ECMP 分散前に各クラスの総入力帯域を上限制限
              ↓
[Layer 2] HTB WRR           (leri-cr1/2/3, cr1/2/3-lere)
          輻輳時に 4:2:1 の帯域比で各クラスを制御
              ↓
[Layer 3] DropTail          (lere-rx1/2/3)
          LER_Egress の出口キューは単純 FIFO 100pkt
```

### 4.2 Layer 1: Ingress Policing

`30_tc.sh` が leri-tx1/2/3 に ingress qdisc + tc police filter を設定する。

```
総帯域 = CR1_BW + CR2_BW + CR3_BW = 300 Mbps (デフォルト)

leri-tx1 (AF41 入力): police rate = 4/7 × 300M = 171 Mbps
leri-tx2 (AF42 入力): police rate = 2/7 × 300M =  86 Mbps
leri-tx3 (AF43 入力): police rate = 1/7 × 300M =  43 Mbps
```

**目的**: ECMP の L4 ハッシュは各ストリームを特定の CoreRouter に固定的に振り分けるため、
異なるクラスが同一リンクで競合しない場合がある。
Ingress policing はルーティング前に帯域を確定させることで、
ECMP 分散の偏りに依存せず比率を保証する。

**burst 計算**:
```
burst = rate[kbps] × 1000 / 8 / 100  (10ms 分のバイト数、最小 16KB)
```

### 4.3 Layer 2: HTB WRR

`30_tc.sh` が LER_Ingress の各 CoreRouter 向け egress インターフェース (leri-cr1/2/3) と
各 CoreRouter の LER_Egress 向け egress インターフェース (cr1/2/3-lere) に
HTB qdisc を設定する。

**クラス構造** (各 100M リンクの例):

```
1:0  root  rate=100M ceil=100M
 ├── 1:1  AF41(高)  rate=57M  ceil=100M  prio=0  quantum=5600
 │    └── 11: netem delay=0ms
 ├── 1:2  AF42(中)  rate=29M  ceil=100M  prio=1  quantum=2800
 │    └── 12: netem delay=10ms   ← LER_Ingress のみ
 └── 1:3  AF43(低)  rate=14M  ceil=100M  prio=2  quantum=1400
      └── 13: netem delay=40ms   ← LER_Ingress のみ
```

- `rate`: 輻輳時の最低保証帯域 (WRR 比 4:2:1)
- `ceil`: バースト時の最大使用帯域 (他クラスが空の場合に借用可能)
- `prio`: 借用帯域の優先度 (低い値が優先)
- `quantum`: ラウンドロビンの重み (パケットサイズ × WRR 重み)

**クラス分類フィルタ**:

| 場所 | フィルタ種別 | 根拠 |
|---|---|---|
| LER_Ingress (leri-cr?) | `fw` classifier (fwmark 41/42/43) | MPLS push 後も skb->mark は保持される |
| CoreRouter (cr?-lere) | `u32` matcher (MPLS 内 IP TOS フィールド) | MPLS ヘッダ (4 byte) の直後の IP TOS バイトを参照 |

CoreRouter の u32 マッチの詳細:
```
protocol 0x8847 (MPLS unicast)
u32 match u32 0x00880000 0x00FC0000 at 4   → TOS=0x88 (AF41, DSCP=34)
u32 match u32 0x00900000 0x00FC0000 at 4   → TOS=0x90 (AF42, DSCP=36)
u32 match u32 0x00980000 0x00FC0000 at 4   → TOS=0x98 (AF43, DSCP=38)
```
`at 4` は MPLS ヘッダ先頭からのオフセット (MPLS ラベル 4 byte の直後 = inner IP ヘッダ先頭)。
マスク `0x00FC0000` は 32bit ワード中の TOS バイト上位 6bit (DSCP フィールド) を抽出する。

**遅延付与** (LER_Ingress の HTB リーフ netem のみ):

クラスごとに異なる netem 遅延を付与することで、
ECMP ハッシュの偏りに依存せず遅延の優先順序 `AF41 < AF42 < AF43` を保証する。
遅延は LER_Ingress の leri-cr? egress にのみ適用し、CoreRouter では適用しない。

| クラス | 追加遅延 (デフォルト) | 設定変数 |
|---|---|---|
| AF41 (高) | 0ms | — |
| AF42 (中) | 10ms | `DELAY_ME` |
| AF43 (低) | 40ms | `DELAY_LO` |

リンク遅延 (`CR?_DELAY`) が設定されている場合はその値に加算される。

**理論スループット** (全 3 リンク, CR_BW=100M):

| クラス | 計算 | 値 |
|---|---|---|
| AF41 | 4/7 × 100M × 3 | 171 Mbps |
| AF42 | 2/7 × 100M × 3 |  86 Mbps |
| AF43 | 1/7 × 100M × 3 |  43 Mbps |
| 合計 | — | 300 Mbps |

### 4.4 Layer 3: DropTail

LER_Egress の lere-rx1/2/3 に pfifo (100 パケット) を設定する。
各インターフェースは 1 クラスのみを転送するため、クラス間競合は発生しない。

### 4.5 優先度制御の適用ポイントまとめ

```
Tx1 ─[police 171M]─ leri-tx1 ─ LER_Ingress
Tx2 ─[police  86M]─ leri-tx2 ─    │
Tx3 ─[police  43M]─ leri-tx3 ─    │
                                   ├─[HTB WRR + netem]─ leri-cr1 ─ CR1 ─[HTB WRR]─ cr1-lere ─ LER_Egress ─[pfifo]─ lere-rx1 ─ Rx1
                                   ├─[HTB WRR + netem]─ leri-cr2 ─ CR2 ─[HTB WRR]─ cr2-lere ─ LER_Egress ─[pfifo]─ lere-rx2 ─ Rx2
                                   └─[HTB WRR + netem]─ leri-cr3 ─ CR3 ─[HTB WRR]─ cr3-lere ─ LER_Egress ─[pfifo]─ lere-rx3 ─ Rx3
```

---

## 5. パケット処理フロー (AF41 の例)

```
1. Tx1 が UDP dport=1000 で 10.2.1.2 宛てパケットを送信

2. LER_Ingress の leri-tx1 に到着
   └─ ingress police: 171M を超える分は drop

3. iptables mangle PREROUTING
   └─ UDP dport=1000 → DSCP AF41 (TOS=0x88)
   └─ dscp AF41      → fwmark=41

4. ip rule: fwmark=41 → table 41 を参照

5. table 41: ECMP nexthop (L4 ハッシュで CR1/CR2/CR3 に分散)
   └─ encap mpls 100 via 10.1.3.2 dev leri-cr1  (CR1 経由の場合)

6. leri-cr1 の HTB WRR
   └─ fw classifier: fwmark=41 → class 1:1 (AF41, rate=57M, prio=0)
   └─ netem delay=0ms → CoreRouter1 へ送信

7. CoreRouter1: MPLS ラベルスワップ
   └─ label 100 → 101, via 10.2.10.1 dev cr1-lere

8. cr1-lere の HTB WRR
   └─ u32 match: MPLS[4].TOS & 0x00FC0000 == 0x00880000 → class 1:1 (AF41)
   └─ LER_Egress へ送信

9. LER_Egress: MPLS pop
   └─ label 101 → IP 転送 → 10.2.1.2 dev lere-rx1

10. lere-rx1 の DropTail (pfifo 100pkt)
    └─ Rx1 へ到達
```

---

## 6. 設定パラメータ (lab_config.sh)

| 変数 | デフォルト | 説明 |
|---|---|---|
| `TX1_RATE` / `TX2_RATE` / `TX3_RATE` | 500M | iperf3 クライアントの送信レート |
| `CR1_BW` / `CR2_BW` / `CR3_BW` | 100M | 各コアリンクの帯域上限 (HTB total rate) |
| `CR1_DELAY` / `CR2_DELAY` / `CR3_DELAY` | 0ms | 各コアリンクに付与するリンク遅延 (全クラス共通) |
| `DELAY_ME` | 10ms | AF42 クラスへの追加遅延 (LER_Ingress egress のみ) |
| `DELAY_LO` | 40ms | AF43 クラスへの追加遅延 (LER_Ingress egress のみ) |

---

## 7. 計測シナリオ

### normal
全 3 リンク ECMP + WRR 優先制御。障害なし。

### failure
t=20s に leri-cr1 (AF41 指定プライマリ) をダウン、t=40s 復旧。
ECMP 経路は静的のまま更新しないため、CR1 に向けたパケットは損失する。

### failure_rsvp
failure と同条件だが `rsvp_monitor.sh` を起動。
CR1 ダウン検知後に ECMP を CR2+CR3 のみで再構築 (MPLS-TE FRR)。
優先度制御は切替先でも継続する。
