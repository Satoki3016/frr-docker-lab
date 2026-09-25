#!/bin/bash
# =============================================================================
# RADWIN TerraNet 無線チェーン検証スクリプト
#
# 用途:
#   ノートPCを KeepLINK-A (ODU-A 側) の空きポートに挿した状態で実行し、
#   60GHz 無線2ホップの疎通・RTT・通過MTU・スループットを確認する。
#   SONiC には一切触れないため、既存の実験環境を壊す心配なく実行できる。
#
# 検証対象のチェーン:
#   [PC]-KeepLINK-A-[.31] )))無線1((( [.32]-中継-[.33] )))無線2((( [.34]-KeepLINK-C
#
# 使い方:
#   bash scripts/radwin_verify.sh <NIC名> [対向PCのIP]
#     例: bash scripts/radwin_verify.sh enp0s31f6
#         bash scripts/radwin_verify.sh enp0s31f6 192.168.1.200
#
#   対向PCのIPを指定すると iperf3 によるスループット測定まで実行する。
#   対向PC側では事前に `iperf3 -s` を起動しておくこと。
# =============================================================================
set -u

NIC="${1:-}"
PEER="${2:-}"
MY_IP="192.168.1.100/24"

# チェーン上の ODU。順番が重要（手前から奥へ）。
ODU_IPS=(192.168.1.31 192.168.1.32 192.168.1.33 192.168.1.34)
ODU_DESC=(
    "ODU-A  有線直結（KeepLINK-A 経由・必ず通るはず）"
    "ODU-B  無線1 を越える"
    "ODU-C  無線1 + 中継 を越える"
    "ODU-D  無線1 + 中継 + 無線2 を越える"
)
# 到達できなかった段で表示する原因。添字は ODU_IPS と対応。
ODU_CAUSE=(
    "KeepLINK-A の配線、PC の IP 設定、または ODU-A の電源"
    "無線1 (ODU-A .31 <-> ODU-B .32) が未確立"
    "中継セグメント (ODU-B .32 <-> ODU-C .33) の有線配線"
    "無線2 (ODU-C .33 <-> ODU-D .34) が未確立"
)

hr() { printf '%s\n' "-------------------------------------------------------------"; }

if [ -z "$NIC" ]; then
    echo "使い方: bash scripts/radwin_verify.sh <NIC名> [対向PCのIP]"
    echo ""
    echo "利用可能な NIC:"
    ip -br link show 2>/dev/null | awk '$1!="lo"{printf "  %s\n", $1}'
    exit 1
fi

if ! ip link show "$NIC" >/dev/null 2>&1; then
    echo "[NG] NIC '$NIC' が見つかりません。"
    exit 1
fi

# -----------------------------------------------------------------------------
# 0. PC 側の準備
# -----------------------------------------------------------------------------
echo "============================================================="
echo " RADWIN 無線チェーン検証   $(date '+%Y-%m-%d %H:%M:%S')"
echo " NIC: $NIC"
echo "============================================================="
echo ""
echo "[0] PC 側の準備"
hr

sudo ip link set "$NIC" up 2>/dev/null
if ip -4 addr show dev "$NIC" | grep -q "192\.168\.1\.100/24"; then
    echo "  192.168.1.100/24 は設定済み"
else
    if sudo ip addr add "$MY_IP" dev "$NIC" 2>/dev/null; then
        echo "  192.168.1.100/24 を $NIC に追加した"
    else
        echo "  [警告] IP を追加できなかった。既に別 IP が付いている可能性がある"
    fi
fi
sudo ip neigh flush all 2>/dev/null && echo "  ARP キャッシュをクリアした"

echo ""
echo "  現在の $NIC:"
ip -br addr show dev "$NIC" | sed 's/^/    /'

# -----------------------------------------------------------------------------
# 1. チェーン疎通確認
# -----------------------------------------------------------------------------
echo ""
echo "[1] チェーン疎通確認（手前から順に ping）"
hr

# 60GHz の TDD はトラフィックが無いとスケジューリングが疎になり、最初のパケットが
# 待たされる。計測順序によって RTT が逆転するため、先に全ホップを温めておく。
echo "  ウォームアップ中（無線のTDDスケジューリングを安定させる）..."
ping -c20 -W2 -i 0.2 "${ODU_IPS[-1]}" >/dev/null 2>&1 || true
echo ""

REACHED=-1
declare -a RTT_AVG
for i in "${!ODU_IPS[@]}"; do
    ip_addr="${ODU_IPS[$i]}"
    printf "  %-15s %s\n" "$ip_addr" "${ODU_DESC[$i]}"
    ping -c3 -W2 -i 0.2 "$ip_addr" >/dev/null 2>&1 || true   # 宛先ごとの助走（ARP解決含む）
    out=$(ping -c20 -W2 -i 0.2 "$ip_addr" 2>/dev/null)
    if echo "$out" | grep -q " 0% packet loss"; then
        rtt=$(echo "$out" | awk -F'/' '/rtt|round-trip/{print $5}')
        RTT_AVG[$i]="$rtt"
        printf "      -> OK    平均RTT %s ms\n" "${rtt:-?}"
        REACHED=$i
    else
        loss=$(echo "$out" | grep -o '[0-9]*% packet loss' | head -1)
        printf "      -> NG    (%s)\n" "${loss:-応答なし}"
        break
    fi
done

echo ""
if [ "$REACHED" -eq $(( ${#ODU_IPS[@]} - 1 )) ]; then
    echo "  [OK] チェーン完成。無線2ホップとも疎通している。"
else
    failed=$(( REACHED + 1 ))
    echo "  [NG] ${ODU_IPS[$failed]} に到達できない。"
    echo "       想定原因: ${ODU_CAUSE[$failed]}"
    echo ""
    echo "  ここで停止する。原因を解消してから再実行すること。"
    exit 1
fi

# ホップごとの RTT 増分（無線区間の遅延の目安）
echo ""
echo "  ホップごとの RTT 増分:"
echo "    （注: 各ODUの管理CPUの応答時間を含むため、伝搬遅延そのものではない。"
echo "      負の値が出る場合は無線が十分に温まっていない。参考値として扱うこと）"
prev=""
for i in "${!ODU_IPS[@]}"; do
    cur="${RTT_AVG[$i]:-}"
    if [ -n "$prev" ] && [ -n "$cur" ]; then
        delta=$(awk -v a="$cur" -v b="$prev" 'BEGIN{printf "%+.3f", a-b}')
        printf "    %s -> %s : %s ms\n" "${ODU_IPS[$((i-1))]}" "${ODU_IPS[$i]}" "$delta"
    fi
    prev="$cur"
done

# -----------------------------------------------------------------------------
# 2. 通過 MTU の確認
# -----------------------------------------------------------------------------
echo ""
echo "[2] 通過 MTU の確認（ODU 設定上限は 7900、ラボ側は 9100）"
hr

TARGET="${ODU_IPS[3]}"
# ping のペイロード長 = MTU - 28 (IPヘッダ20 + ICMPヘッダ8)
probe_mtu() { ping -c2 -W2 -M do -s "$(( $1 - 28 ))" "$TARGET" >/dev/null 2>&1; }

# 送信元 NIC の MTU が小さいと経路ではなく PC 側で頭打ちになる。先に引き上げる。
ORIG_MTU=$(cat "/sys/class/net/$NIC/mtu" 2>/dev/null || echo 1500)
NIC_MTU_RAISED=0
if [ "$ORIG_MTU" -lt 7900 ]; then
    if sudo ip link set dev "$NIC" mtu 7900 2>/dev/null; then
        NIC_MTU_RAISED=1
        echo "  送信元 NIC の MTU を 7900 に引き上げた（元: $ORIG_MTU。測定後に戻す）"
    else
        echo "  [警告] NIC '$NIC' の MTU を 7900 にできなかった（現在 $ORIG_MTU）。"
        echo "         この NIC がジャンボフレーム非対応の可能性がある。"
        echo "         以下の測定値は経路ではなく NIC の上限を見ている恐れがあるので注意。"
    fi
else
    echo "  送信元 NIC の MTU は $ORIG_MTU（引き上げ不要）"
fi

if probe_mtu 7900; then
    PASS_MTU=7900
    echo "  7900 通過。ODU の設定上限どおり。"
else
    lo=576; hi=7900
    echo "  7900 は通らない。二分探索で上限を特定する..."
    if ! probe_mtu $lo; then
        PASS_MTU=0
    else
        while [ $(( hi - lo )) -gt 1 ]; do
            mid=$(( (lo + hi) / 2 ))
            if probe_mtu $mid; then lo=$mid; else hi=$mid; fi
        done
        PASS_MTU=$lo
    fi
    echo "  通過可能な最大 MTU: $PASS_MTU"
fi

echo ""
if [ "${PASS_MTU:-0}" -ge 7900 ]; then
    echo "  [OK] MTU 7900 で問題なし。"
elif [ "${PASS_MTU:-0}" -ge 7000 ]; then
    echo "  [OK] MTU $PASS_MTU まで通る。ODU の設定上限 7900 とほぼ一致しており、"
    echo "       経路にジャンボフレームの制約は無い。ラボ側 (9100) より小さいので、"
    echo "       frr_setup.sh の cr1-lere / lere-cr1 をこの値に合わせること。"
elif [ "${PASS_MTU:-0}" -ge 1500 ]; then
    echo "  [注意] MTU が $PASS_MTU に制限されている。"
    if [ "$NIC_MTU_RAISED" = "0" ] && [ "$ORIG_MTU" -lt 7900 ]; then
        echo "         ただし送信元 NIC の MTU が $ORIG_MTU のままなので、"
        echo "         これは経路ではなく PC 側の上限を見ている可能性が高い。"
        echo "         NIC の MTU を上げてから再測定すること。"
    else
        echo "         送信元 NIC は引き上げ済みなので、経路上の機器"
        echo "         （KeepLINK / 中継部 / ODU）がジャンボフレーム非対応。"
    fi
    echo "         frr_setup.sh の cr1-lere / lere-cr1 をこの値に合わせるか、"
    echo "         OSPF に mtu-ignore が必要になる（DBD で MTU 照合するため）。"
else
    echo "  [NG] MTU 測定に失敗、または極端に小さい。経路を確認すること。"
fi

# NIC の MTU を元に戻す（他の通信への影響を避けるため）
if [ "$NIC_MTU_RAISED" = "1" ]; then
    sudo ip link set dev "$NIC" mtu "$ORIG_MTU" 2>/dev/null \
        && echo "  送信元 NIC の MTU を $ORIG_MTU に戻した"
fi

# -----------------------------------------------------------------------------
# 3. スループット測定
# -----------------------------------------------------------------------------
echo ""
echo "[3] スループット測定（CR_BW の根拠）"
hr

if [ -z "$PEER" ]; then
    echo "  対向PCのIPが未指定のためスキップ。"
    echo ""
    echo "  測定するには対向PCを KeepLINK-C (ODU-D 側) に挿し、"
    echo "    対向PC:  sudo ip addr add 192.168.1.200/24 dev <NIC>; iperf3 -s"
    echo "    こちら:  bash scripts/radwin_verify.sh $NIC 192.168.1.200"
    echo ""
    echo "  PCが1台しかない場合は、ODU 管理画面の Wireless Status にある"
    echo "  TX/RX SpeedTest で各ホップ単体のスループットを測れる。"
elif ! command -v iperf3 >/dev/null 2>&1; then
    echo "  [NG] iperf3 が見つからない。scripts/get_iperf3.sh を参照。"
else
    echo "  TCP で上限を把握:"
    iperf3 -c "$PEER" -t 20 2>/dev/null | tail -4 | sed 's/^/    /'

    echo ""
    echo "  UDP で損失が出始める点を探す（実験は UDP なのでこちらを採用）:"
    printf "    %-8s %-14s %-10s\n" "指定" "実効" "損失"
    for rate in 500M 1G 1500M 2G; do
        res=$(iperf3 -c "$PEER" -u -b "$rate" -t 15 2>/dev/null | grep -E "receiver" | tail -1)
        bw=$(echo "$res"   | awk '{for(i=1;i<=NF;i++) if($i=="Mbits/sec"||$i=="Gbits/sec"){print $(i-1)" "$i; exit}}')
        loss=$(echo "$res" | grep -o '([0-9.]*%)' | tail -1)
        printf "    %-8s %-14s %-10s\n" "$rate" "${bw:-?}" "${loss:-?}"
    done
    echo ""
    echo "  損失が出始める直前のレートが実効容量。"
    echo "  CR_BW = 実効容量 x 0.9 とし、lab_config_c2.sh の"
    echo "  CR1_BW / CR2_BW / CR3_BW を全て同じ値に揃えること。"
fi

# -----------------------------------------------------------------------------
echo ""
echo "============================================================="
echo " 完了。この出力を記録しておくこと（CR_BW と MTU の根拠になる）"
echo "============================================================="
