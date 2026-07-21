#!/bin/bash
# C1物理ファブリック環境用パラメータ (LAB_MODE=c1)
#
# 構成: コンテナ群はPC(virttrx)上、コアリンク3本は
#   PC 10G NIC → SW1 ASIC → クロスケーブル → SW2 ASIC → PC 10G NIC
#   (VLAN 101/102/103 で論理分離。KNET/CPU puntを通らないため10G可)
#
# CR_BW=9G の根拠: 物理ワイヤ10Gに対しHTBが厳密にボトルネックであることを
# 保証するため10%マージンを確保 (2026-07-16 Phase3実測: ファブリック素通し
# 9.9G無損失を確認済み)。
#
# 期待値 (HTB保証1/10縮小方式、C=9G, 全クラス需要8G):
#   AF41: 8G無損失 (保証0.9G + Yellow借用で需要8G < 供給8.61G)
#   AF42: ≈0.67G (保証0.257G + 残余Yellow 2/3)
#   AF43: ≈0.44G (保証0.129G + 残余Yellow 1/3)

TX1_RATE="${TX1_RATE:-2G}"    # AF41: 4×2G=8G < 9G → SP保護で無損失目標
TX2_RATE="${TX2_RATE:-2G}"    # AF42: 4×2G=8G >> 2/7×9G=2.57G → 意図的輻輳
TX3_RATE="${TX3_RATE:-2G}"    # AF43: 4×2G=8G >> 1/7×9G=1.29G → 意図的輻輳

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

# C1ファブリックNIC割り当て (frr_setup.sh が参照)
C1_NIC_SW1="${C1_NIC_SW1:-enp5s0f1}"   # → SW1:Ethernet17
C1_NIC_SW2="${C1_NIC_SW2:-enp5s0f0}"   # → SW2:Ethernet10
