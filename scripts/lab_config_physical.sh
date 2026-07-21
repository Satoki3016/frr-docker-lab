#!/bin/bash
# 物理2SW環境用パラメータ
# CR=30M（KNETのCoPP制限内で確認済みの最大値）
# 単一iperf3ストリーム (-P 1) で各クラスを送信
#
# 設計根拠:
#   SP割当: 4/7×30M ≈ 17.14M  WRR_ME割当: 2/7×30M ≈ 8.57M  WRR_LO割当: 1/7×30M ≈ 4.28M
#   AF41: 12M  < SP割当 17.14M  → SP保護で無損失を実証
#   AF42: 20M >> WRR割当  8.57M  → 輻輳 (損失率~57%)
#   AF43: 20M >> WRR割当  4.28M  → 輻輳 (損失率~79%)
#   総送信量: 12+20+20=52M >> 30M（1.73倍オーバーサブスクリプション）

TX1_RATE="${TX1_RATE:-12M}"    # AF41: 12M  < SP割当 17.14M → 無損失目標
TX2_RATE="${TX2_RATE:-20M}"    # AF42: 20M >> WRR割当  8.57M → 意図的輻輳
TX3_RATE="${TX3_RATE:-20M}"    # AF43: 20M >> WRR割当  4.28M → 意図的輻輳

CR1_BW="${CR1_BW:-30M}"        # KNETのCoPP制限内で確認済みの最大値
CR2_BW="${CR2_BW:-30M}"
CR3_BW="${CR3_BW:-30M}"

CR1_DELAY="${CR1_DELAY:-0ms}"
CR2_DELAY="${CR2_DELAY:-0ms}"
CR3_DELAY="${CR3_DELAY:-0ms}"

WRR_HI="${WRR_HI:-4}"
WRR_ME="${WRR_ME:-2}"
WRR_LO="${WRR_LO:-1}"

PFIFO_LIMIT_HI="${PFIFO_LIMIT_HI:-1000}"
PFIFO_LIMIT_ME="${PFIFO_LIMIT_ME:-2000}"
PFIFO_LIMIT_LO="${PFIFO_LIMIT_LO:-4000}"
