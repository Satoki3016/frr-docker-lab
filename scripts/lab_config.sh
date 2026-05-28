#!/bin/bash
# ラボ設定ファイル

TX1_RATE="${TX1_RATE:-500M}"
TX2_RATE="${TX2_RATE:-500M}"
TX3_RATE="${TX3_RATE:-500M}"

CR1_BW="${CR1_BW:-100M}"
CR2_BW="${CR2_BW:-100M}"
CR3_BW="${CR3_BW:-100M}"

CR1_DELAY="${CR1_DELAY:-0ms}"
CR2_DELAY="${CR2_DELAY:-0ms}"
CR3_DELAY="${CR3_DELAY:-0ms}"

# クラス別追加遅延 (LER_Ingress egress の HTB リーフで付与)
# ECMP ハッシュに依存せず AF41 < AF42 < AF43 の遅延順序を保証する
DELAY_ME="${DELAY_ME:-10ms}"   # AF42 中優先クラスへの追加遅延
DELAY_LO="${DELAY_LO:-40ms}"   # AF43 低優先クラスへの追加遅延

# WRR 重み比率 (AF41:AF42:AF43)
WRR_HI="${WRR_HI:-4}"   # AF41 高優先の重み
WRR_ME="${WRR_ME:-2}"   # AF42 中優先の重み
WRR_LO="${WRR_LO:-1}"   # AF43 低優先の重み

# netem キュー長 (パケット数) — 最大キュー遅延を制御
# 制約: AF41 最大キュー遅延 < DELAY_ME(10ms)
#   NETEM_LIMIT ≤ DELAY_ME × (WRR_HI/WRR_sum × CR_BW) / (1400×8)
#   = 10ms × (4/7 × 100M) / 11200 ≈ 50  → 余裕を持たせ 30 に設定
# limit=30 での各クラス最大 RTT: AF41≤6ms, AF42≤22ms, AF43≤64ms
NETEM_LIMIT="${NETEM_LIMIT:-30}"
