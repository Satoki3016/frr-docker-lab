#!/bin/bash
# veth（仮想環境）用パラメータ
# CR=10G、総送信24G（2.4倍オーバーサブスクリプション）
# AF41(8G)はリンク容量10G以内 → SP最優先で無損失を実証

TX1_RATE="${TX1_RATE:-2G}"    # AF41: 4×2G=8G  < リンク10G → SP最優先で無損失
TX2_RATE="${TX2_RATE:-2G}"    # AF42: 4×2G=8G >> WRR割当 2/7×10G=2.86G → 意図的輻輳（超過率2.8倍）
TX3_RATE="${TX3_RATE:-2G}"    # AF43: 4×2G=8G >> WRR割当 1/7×10G=1.43G → 意図的輻輳（超過率5.6倍）

CR1_BW="${CR1_BW:-10G}"
CR2_BW="${CR2_BW:-10G}"
CR3_BW="${CR3_BW:-10G}"

CR1_DELAY="${CR1_DELAY:-0ms}"
CR2_DELAY="${CR2_DELAY:-0ms}"
CR3_DELAY="${CR3_DELAY:-0ms}"

WRR_HI="${WRR_HI:-4}"
WRR_ME="${WRR_ME:-2}"
WRR_LO="${WRR_LO:-1}"

PFIFO_LIMIT_HI="${PFIFO_LIMIT_HI:-1000}"
PFIFO_LIMIT_ME="${PFIFO_LIMIT_ME:-2000}"
PFIFO_LIMIT_LO="${PFIFO_LIMIT_LO:-4000}"
