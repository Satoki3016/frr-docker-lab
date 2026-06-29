#!/bin/bash
# ラボ設定ファイル

# AF41(SP)はCR_BWの60%送信 → SP優先で全量通過 (6G > 4/7×10G≈5.71G を僅かに上回る)
# AF42/AF43は10G送信 → 輻輳下で残り4GをWRR 2:1分配 (AF42≈2.67G, AF43≈1.33G)
TX1_RATE="${TX1_RATE:-6G}"
TX2_RATE="${TX2_RATE:-10G}"
TX3_RATE="${TX3_RATE:-10G}"

# CRリンクのHTB rate = 輻輳ポイント (合計送信26G >> 10G → 2.6倍輻輳)
# 物理クロスSWリンク: SW1:Eth14 ↔ SW2:Eth2 は10G物理ポート
CR1_BW="${CR1_BW:-10G}"
CR2_BW="${CR2_BW:-10G}"
CR3_BW="${CR3_BW:-10G}"

CR1_DELAY="${CR1_DELAY:-0ms}"
CR2_DELAY="${CR2_DELAY:-0ms}"
CR3_DELAY="${CR3_DELAY:-0ms}"

# スケジューリング方式: SP + WRR
#   AF41: Strict Priority (prio 0) — 常に最優先でサービス
#   AF42/AF43: WRR (prio 1) — AF41 充足後に重み比率でサービス
# → 人工遅延(netem)なし。輻輳時の自然なキュー待ち時間差でクラス差別化

# WRR 重み比率 (AF42:AF43 間のみ適用)
WRR_HI="${WRR_HI:-4}"   # AF41 Strict Priority (quantum のみ使用)
WRR_ME="${WRR_ME:-2}"   # AF42 WRR 重み
WRR_LO="${WRR_LO:-1}"   # AF43 WRR 重み

# pfifo キュー長 (パケット数) — HTB リーフ qdisc
# 10G×4/7≈5.71G, 1400B/pkt → AF41 max 遅延 ≈ 1000×1400×8/5.71G ≈ 2.0ms
# 10G×1/7≈1.43G            → AF43 max 遅延 ≈ 4000×1400×8/1.43G  ≈ 31.3ms
PFIFO_LIMIT_HI="${PFIFO_LIMIT_HI:-1000}"   # AF41: SP優先のため浅いキュー
PFIFO_LIMIT_ME="${PFIFO_LIMIT_ME:-2000}"   # AF42
PFIFO_LIMIT_LO="${PFIFO_LIMIT_LO:-4000}"   # AF43: 低優先のため深いキュー
