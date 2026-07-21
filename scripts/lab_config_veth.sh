#!/bin/bash
# veth（仮想環境）用パラメータ
# CR=9G、総送信24G（2.67倍オーバーサブスクリプション）
# AF41(8G)はリンク容量9G以内 → SP最優先で無損失を実証
# 2026-07-21: 全環境(veth/C1/C2)でCR帯域を統一するため 10G→9G に変更。
# C1/C2は物理10Gワイヤに対しHTBが確実にボトルネックになるよう9Gにしており、
# 公平な横比較のためvethも同一の9Gに揃えた（TX側は元々全環境8G/クラスで同一）。

TX1_RATE="${TX1_RATE:-2G}"    # AF41: 4×2G=8G  < リンク9G → SP最優先で無損失
TX2_RATE="${TX2_RATE:-2G}"    # AF42: 4×2G=8G >> WRR割当 2/7×9G=2.57G → 意図的輻輳
TX3_RATE="${TX3_RATE:-2G}"    # AF43: 4×2G=8G >> WRR割当 1/7×9G=1.29G → 意図的輻輳

CR1_BW="${CR1_BW:-9G}"
CR2_BW="${CR2_BW:-9G}"
CR3_BW="${CR3_BW:-9G}"

CR1_DELAY="${CR1_DELAY:-0ms}"
CR2_DELAY="${CR2_DELAY:-0ms}"
CR3_DELAY="${CR3_DELAY:-0ms}"

WRR_HI="${WRR_HI:-4}"
WRR_ME="${WRR_ME:-2}"
WRR_LO="${WRR_LO:-1}"

PFIFO_LIMIT_HI="${PFIFO_LIMIT_HI:-1000}"
PFIFO_LIMIT_ME="${PFIFO_LIMIT_ME:-2000}"
PFIFO_LIMIT_LO="${PFIFO_LIMIT_LO:-4000}"
