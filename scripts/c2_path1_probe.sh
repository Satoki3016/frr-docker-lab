#!/bin/bash
# 経路1(無線2ホップ)の実容量を切り分けるための測定。
# c2_fabric_test.sh を実行済みで netns c2a1/c2b1 が存在する状態で使う。
#   sudo bash scripts/c2_path1_probe.sh
set -u
NS_A=c2a1; NS_B=c2b1; DST=10.99.1.2

if ! ip netns list | grep -qw "$NS_A"; then
  echo "[NG] netns $NS_A が無い。先に sudo bash scripts/c2_fabric_test.sh を実行すること。"
  exit 1
fi

ip netns exec "$NS_B" pkill -f iperf3 2>/dev/null || true
sleep 1
ip netns exec "$NS_B" iperf3 -s -D
sleep 1
trap 'ip netns exec "$NS_B" pkill -f iperf3 2>/dev/null || true' EXIT

echo "=== [A] TCP (自己調整するので「無損失で出せる上限」が分かる) ==="
for n in 1 2; do
  printf "  試行%d: " "$n"
  ip netns exec "$NS_A" iperf3 -c "$DST" -t 10 -O 2 -J 2>/dev/null \
    | python3 -c "
import json,sys
try: d=json.load(sys.stdin)
except Exception: print('測定失敗'); raise SystemExit
s=d.get('end',{}).get('sum_received') or d.get('end',{}).get('sum_sent')
print(f\"{s['bits_per_second']/1e9:.3f} Gbps\" if s else '測定失敗')
"
done

echo ""
echo "=== [B] UDP レートスイープ (損失が出始める点を探す) ==="
printf "  %-9s %-14s %-12s %s\n" "指定" "実効" "損失" "判定"
for r in 500M 1000M 1500M 2000M 2200M 2400M; do
  ip netns exec "$NS_A" iperf3 -u -c "$DST" -b "$r" -l 7000 -t 10 -O 2 -J > /tmp/p1_$r.json 2>/dev/null || true
  python3 -c "
import json
try: d=json.load(open('/tmp/p1_$r.json'))
except Exception: print('  $r        測定失敗'); raise SystemExit
s=d.get('end',{}).get('sum')
if not s: print('  $r        測定失敗'); raise SystemExit
sent=s['bytes']*8/s['seconds']/1e9; loss=s.get('lost_percent',-1)
recv=sent*(1-loss/100)
mark='OK' if loss<2 else ('やや損失' if loss<10 else '容量超過')
print(f'  {\"$r\":<9} {recv:>8.3f} Gbps  {loss:>7.3f}%    {mark}')
"
  sleep 2
done

echo ""
echo "=== [C] 小さいデータグラムでも確認 (-l 1400) ==="
printf "  %-9s %-14s %-12s\n" "指定" "実効" "損失"
for r in 1000M 2000M; do
  ip netns exec "$NS_A" iperf3 -u -c "$DST" -b "$r" -l 1400 -t 10 -O 2 -J > /tmp/p1s_$r.json 2>/dev/null || true
  python3 -c "
import json
try: d=json.load(open('/tmp/p1s_$r.json'))
except Exception: print('  $r        測定失敗'); raise SystemExit
s=d.get('end',{}).get('sum')
if not s: print('  $r        測定失敗'); raise SystemExit
sent=s['bytes']*8/s['seconds']/1e9; loss=s.get('lost_percent',-1)
print(f'  {\"$r\":<9} {sent*(1-loss/100):>8.3f} Gbps  {loss:>7.3f}%')
"
  sleep 2
done

echo ""
echo "=== 読み方 ==="
echo "  [A] TCP が 2 Gbps 台なら無線は正常。1 Gbps 未満なら無線が劣化している。"
echo "  [B] 損失 2% 未満の最大レートが実容量。CR_BW はその 0.9 倍。"
echo "  [C] [B] と大きく違うなら、パケット長依存 (PCのCPU or 無線の集約効率) の問題。"
