#!/bin/bash
# C2 (3独立経路) ファブリック開通試験
# PC(virttrx)上で実行: sudo bash scripts/c2_fabric_test.sh
#
# 各経路はタグなし専用線のため、VLANサブIF不要で直接IPを振って試験する。
#
# 経路1(CR1): 2026-09-08 より 60GHz 無線2ホップ経由 (RADWIN TerraNet V90 x4)
#   enp5s0f1 -> SW1:Eth18 -[VLAN211]- SW1:Eth24 -> KeepLINK-A -> ODU-A(.31)
#     )))無線1 ch1((( ODU-B(.32) -中継- ODU-C(.33) )))無線2 ch4((( ODU-D(.34)
#   -> KeepLINK-C -> SW2:Eth18 -[VLAN211]- SW2:Eth11 -> enp5s0f0
#   実測: 通過MTU 7899 / ボトルネックは無線2の TX 2438 Mbps
# 経路2(CR2): enp23s0f0np0  -> SW1:Eth16->Eth20 -> SW2:Eth12->Eth7  -> enp23s0f1np1 (有線10G)
# 経路3(CR3): enp179s0f0np0 -> SW1:Eth19->Eth0  -> SW2:Eth0->Eth5   -> enp179s0f1np1 (有線10G)
set -e

declare -A PAIRS=(
  [1]="enp5s0f1 enp5s0f0"
  [2]="enp23s0f0np0 enp23s0f1np1"
  [3]="enp179s0f0np0 enp179s0f1np1"
)

# 経路ごとの試験パラメータ。経路1は無線なので MTU も送信レートも有線と異なる。
# MTU: 無線経路の通過MTUは実測 7899。ジャンボ試験のデータグラム長もこれに収める。
declare -A PATH_MTU=(   [1]=7800   [2]=9100   [3]=9100   )
declare -A PATH_RATE=(  [1]=2400M  [2]=9500M  [3]=9500M  )
declare -A PATH_DGRAM=( [1]=7000   [2]=8950   [3]=8950   )
declare -A PATH_DESC=(  [1]="無線2ホップ" [2]="有線" [3]="有線" )

echo "=== [1] クリーンアップ ==="
# netns 内に iperf3 が残っていると名前空間の参照が残り、ip netns del しても
# 物理NICが root netns に戻らない (名前だけ消えて「迷子」になる)。
# 前回が異常終了した場合に必ず起きるので、先にプロセスを落とす。
for n in c2a1 c2b1 c2a2 c2b2 c2a3 c2b3; do
  ip netns exec "$n" pkill -f iperf3 2>/dev/null || true
done
pkill -f 'iperf3 -s' 2>/dev/null || true   # 名前が既に消えた netns の残骸も回収
sleep 1
for n in c2a1 c2b1 c2a2 c2b2 c2a3 c2b3; do
  ip netns del "$n" 2>/dev/null || true
done

# 物理NICが root netns に戻るまで待つ (netns 解放は非同期)
for _try in 1 2 3 4 5 6 7 8 9 10; do
  _missing=""
  for i in 1 2 3; do
    read -r _a _b <<< "${PAIRS[$i]}"
    ip link show "$_a" >/dev/null 2>&1 || _missing="$_missing $_a"
    ip link show "$_b" >/dev/null 2>&1 || _missing="$_missing $_b"
  done
  [ -z "$_missing" ] && break
  sleep 1
done
if [ -n "$_missing" ]; then
  echo "  [NG] 次のNICが root netns に戻っていない:$_missing"
  echo ""
  # NICが今どこに居るのかを実際に探して報告する。
  # 実験コンテナ(LER_Ingress/CR1/...)が起動中だと、そちらがNICを保持している。
  _in_container=0
  for _n in $_missing; do
    _found=""
    for _ns in $(ip netns list 2>/dev/null | awk '{print $1}'); do
      if ip netns exec "$_ns" ip link show "$_n" >/dev/null 2>&1; then
        _found="$_ns"; break
      fi
    done
    if [ -n "$_found" ]; then
      echo "    $_n → netns '$_found' が保持"
      case "$_found" in CR1|CR2|CR3|LER_Ingress|LER_Egress) _in_container=1 ;; esac
    else
      echo "    $_n → 名前の無い netns (プロセスが掴んでいる)"
    fi
  done
  echo ""
  if [ "$_in_container" = "1" ]; then
    echo "  実験コンテナが起動中です。先に停止してください:"
    echo "    sudo bash scripts/frr_down.sh"
    echo "    sudo bash scripts/c2_fabric_test.sh   # その後で再実行"
  else
    echo "  名前空間を掴んでいるプロセスが残っています。以下で復旧してください:"
    echo "    sudo pkill -f iperf3"
    echo "    sudo ip netns list          # 残っている netns を確認"
    echo "    sudo ip netns del <名前>    # 全部消す"
    echo "    sleep 2 && ip -br link      # NICが戻ったか確認"
  fi
  exit 1
fi
echo "  [ok] 6本のNICすべてが root netns にある"

echo "=== [2] netns割り当て + IP付与 (MTUは経路ごと) ==="
for i in 1 2 3; do
  read -r nicA nicB <<< "${PAIRS[$i]}"
  nsA="c2a${i}"; nsB="c2b${i}"
  mtu="${PATH_MTU[$i]}"
  ip netns add "$nsA"
  ip netns add "$nsB"
  ip link set "$nicA" netns "$nsA"
  ip link set "$nicB" netns "$nsB"
  ip netns exec "$nsA" ip link set "$nicA" up mtu "$mtu"
  ip netns exec "$nsB" ip link set "$nicB" up mtu "$mtu"
  ip netns exec "$nsA" ip addr add 10.99.${i}.1/30 dev "$nicA"
  ip netns exec "$nsB" ip addr add 10.99.${i}.2/30 dev "$nicB"
  ip netns exec "$nsA" ip link set lo up
  ip netns exec "$nsB" ip link set lo up
  echo "  [ok] 経路${i}(${PATH_DESC[$i]}): $nicA(10.99.${i}.1) <-> $nicB(10.99.${i}.2)  MTU $mtu"
done

echo ""
echo "=== [3] 疎通確認 (ping) ==="
for i in 1 2 3; do
  echo "--- 経路${i} (${PATH_DESC[$i]}) ---"
  ip netns exec "c2a${i}" ping -c3 -W2 10.99.${i}.2 | tail -3
  # 設定MTUがそのまま通るか (フラグメント禁止で最大長を1回だけ確認)
  psz=$(( ${PATH_MTU[$i]} - 28 ))
  if ip netns exec "c2a${i}" ping -c2 -W2 -M do -s "$psz" 10.99.${i}.2 >/dev/null 2>&1; then
    echo "  [ok] MTU ${PATH_MTU[$i]} 通過"
  else
    echo "  [NG] MTU ${PATH_MTU[$i]} が通らない。経路上の機器のジャンボ対応を確認すること"
  fi
done

echo ""
# ---------------------------------------------------------------------------
# [4] 単独測定 — 各経路の「実容量」はこちらで判定する。
#
# 3経路同時の最大レート試験は PC 本体の CPU/PCIe が先に頭打ちになるため
# (実測で合計 10.7 Gbps 程度)、経路の実力を測れない。実験では 3 クラスとも
# CR1 が唯一の実働経路 (frr_dscp_te.sh:138-148) で CR2/CR3 は待機なので、
# 3 経路が同時に最大レートで流れる場面は無い。CR_BW の根拠は単独測定を使う。
# ---------------------------------------------------------------------------
echo "=== [4] 単独測定 (1経路ずつ。CR_BW の根拠はこちら) ==="
for i in 1 2 3; do
  ip netns exec "c2b${i}" pkill -f iperf3 2>/dev/null || true
done
sleep 1
for i in 1 2 3; do
  ip netns exec "c2b${i}" iperf3 -s -D
done
sleep 1

for i in 1 2 3; do
  echo "--- 経路${i} (${PATH_DESC[$i]}) 単独 UDP ${PATH_RATE[$i]} ---"
  ip netns exec "c2a${i}" iperf3 -u -c 10.99.${i}.2 -b "${PATH_RATE[$i]}" -l "${PATH_DGRAM[$i]}" \
      -t 10 -O 2 -J > "/tmp/c2_solo${i}.json" 2>/dev/null || true
  python3 -c "
import json,sys
try:
    d=json.load(open('/tmp/c2_solo${i}.json'))
except Exception as e:
    print(f'  [NG] 結果JSONを読めない: {e}'); sys.exit(0)
if 'error' in d:
    print(f\"  [NG] iperf3 エラー: {d['error']}\"); sys.exit(0)
s=d.get('end',{}).get('sum')
if not s:
    print('  [NG] 測定結果なし'); sys.exit(0)
sent=s['bytes']*8/s['seconds']/1e9
loss=s.get('lost_percent',-1)
recv=sent*(1-loss/100) if loss>=0 else float('nan')
print(f'  送信 {sent:.3f} Gbps / 損失 {loss:.4f}% / 実効 {recv:.3f} Gbps')
if loss > 2:
    print(f'    -> 損失が大きい。実容量は約 {recv:.2f} Gbps。CR_BW は {recv*0.9:.2f}G 相当が目安')
else:
    print(f'    -> 損失は小さい。この送信レートは容量内。CR_BW は {sent*0.9:.2f}G 相当が目安')
" || true
done

echo ""
echo "=== [5] 同時実行 (相互干渉の確認のみ。PC の CPU/PCIe 限界が支配的) ==="
echo "  注: 合計送信が PC の処理能力 (実測 約10.7Gbps) を超えるため、"
echo "      ここでの損失は経路の問題ではない。容量判定には [4] を使うこと。"
for i in 1 2 3; do
  ip netns exec "c2b${i}" pkill iperf3 2>/dev/null || true
done
sleep 1
for i in 1 2 3; do
  ip netns exec "c2b${i}" iperf3 -s -D
done
sleep 1

for i in 1 2 3; do
  ip netns exec "c2a${i}" iperf3 -u -c 10.99.${i}.2 -b "${PATH_RATE[$i]}" -l "${PATH_DGRAM[$i]}" -t 10 -O 2 -J > /tmp/c2_path${i}.json &
done
wait

for i in 1 2 3; do
  echo "--- 経路${i} (${PATH_DESC[$i]}) 同時 UDP ${PATH_RATE[$i]} ---"
  python3 -c "
import json,sys
try:
    d=json.load(open('/tmp/c2_path${i}.json'))
except Exception as e:
    print(f'  [NG] 結果JSONを読めない: {e}'); sys.exit(0)
if 'error' in d:
    print(f\"  [NG] iperf3 エラー: {d['error']}\"); sys.exit(0)
s=d.get('end',{}).get('sum')
if not s:
    print('  [NG] 測定結果なし (iperf3が正常に完了していない)'); sys.exit(0)
sent=s['bytes']*8/s['seconds']/1e9
loss=s.get('lost_percent',-1)
recv=sent*(1-loss/100) if loss>=0 else float('nan')
print(f'  送信 {sent:.3f} Gbps / 損失 {loss:.4f}% / 実効 {recv:.3f} Gbps')
" || true
done

for i in 1 2 3; do
  ip netns exec "c2b${i}" pkill iperf3 2>/dev/null || true
done

echo ""
echo "=== 完了 (netns c2a1/b1〜c2a3/b3 は残置。削除: sudo bash -c 'for n in c2a1 c2b1 c2a2 c2b2 c2a3 c2b3; do ip netns del \$n; done') ==="
