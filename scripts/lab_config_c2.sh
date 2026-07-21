#!/bin/bash
# C2完全独立3経路環境用パラメータ (LAB_MODE=c2)
#
# 構成: コンテナ群はPC(virttrx)上、コアリンク3本はそれぞれ専用の物理NICペアで
#   PC 10G NIC → SW1 ASIC → 専用クロスケーブル → SW2 ASIC → PC 10G NIC
#   (VLAN 201/202/203でアクセスポート化。C1と異なり1リンク1クラス専用、VLANタグ不要)
#
# C1からの変更点: 3経路が物理的に完全独立のため、他クラスとのワイヤ共有を
# 気にする必要がない。CR_BW=9GはC1と同じ理由(HTBが厳密にボトルネックである
# ことを保証する10%マージン)で踏襲。TX_RATEもC1と同一(2G×4=8G/クラス)とし、
# veth/C1/C2で理論値を横並びに比較できるようにする。
#
# 2026-07-21 Phase検証: 9本の配線をflapテストで確認済み、3経路とも疎通(損失0%)。
# 生ファブリック(HTB整形なし)での3系統同時9.5Gテストでは経路2/3に大きな損失が
# 出たが、これはPC本体のCPU/PCIe限界であり、HTB整形後の実需要(最大8G級)なら
# 問題にならないと判断(project_c2_independent_paths.md参照)。
#
# 期待値 (HTB保証1/10縮小方式、C=9G, 全クラス需要8G。C1と同一):
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

# C2完全独立3経路のNIC割り当て (frr_setup.sh の連想配列 C2_NIC_SW1/SW2 が参照する値と一致させること)
# 経路1(CR1): enp5s0f1 <-> enp5s0f0
# 経路2(CR2): enp23s0f0np0 <-> enp23s0f1np1
# 経路3(CR3): enp179s0f0np0 <-> enp179s0f1np1
