#!/bin/bash
# スループット計測モニター
# LER_Egress の lere-rx1/2/3 tx_bytes を毎秒ポーリングして CSV に保存
# (Rx1/Rx2/Rx3 への送信量 = 受信量に等しい)
#
# 使い方: bash throughput_monitor.sh <results_dir>
# 出力:   <results_dir>/throughput.csv

RESULTS_DIR="$1"
INTERVAL=1

# LER_Egress namespace から3インターフェース統計を一括取得
get_all_bytes() {
    ip netns exec LER_Egress_ns bash -c "
        cat /sys/class/net/lere-rx1/statistics/tx_bytes
        cat /sys/class/net/lere-rx2/statistics/tx_bytes
        cat /sys/class/net/lere-rx3/statistics/tx_bytes
    " 2>/dev/null
}

# ループ前にベースライン収集 (3行を個別に read)
{ read -r prev1; read -r prev2; read -r prev3; } < <(get_all_bytes)
prev1=${prev1:-0}; prev2=${prev2:-0}; prev3=${prev3:-0}
t_start_ms=$(date +%s%3N)
t_prev_ms=$t_start_ms

echo "time,rx1_bytes_per_sec,rx2_bytes_per_sec,rx3_bytes_per_sec" \
    > "$RESULTS_DIR/throughput.csv"

while true; do
    sleep "$INTERVAL"

    { read -r b1; read -r b2; read -r b3; } < <(get_all_bytes)

    # 取得失敗 (空) の場合はスキップ
    if ! [[ "$b1" =~ ^[0-9]+$ && "$b2" =~ ^[0-9]+$ && "$b3" =~ ^[0-9]+$ ]]; then
        continue
    fi

    now_ms=$(date +%s%3N)
    t=$(( (now_ms - t_start_ms) / 1000 ))       # 表示用: 秒(整数)
    dt_ms=$(( now_ms - t_prev_ms ))              # 実際の経過時間(ミリ秒)
    [ "$dt_ms" -le 0 ] && dt_ms=1000

    # bytes/ms × 1000 = bytes/s (整数演算で精度を保つ)
    d1=$(( (b1 - prev1) * 1000 / dt_ms ))
    d2=$(( (b2 - prev2) * 1000 / dt_ms ))
    d3=$(( (b3 - prev3) * 1000 / dt_ms ))
    [ "$d1" -lt 0 ] && d1=0
    [ "$d2" -lt 0 ] && d2=0
    [ "$d3" -lt 0 ] && d3=0

    echo "$t,$d1,$d2,$d3" >> "$RESULTS_DIR/throughput.csv"

    prev1=$b1; prev2=$b2; prev3=$b3
    t_prev_ms=$now_ms
done
