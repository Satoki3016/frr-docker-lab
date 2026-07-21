#!/bin/bash
set -e
for i in 1 2 3; do
  ip netns exec "c2b${i}" pkill iperf3 2>/dev/null || true
done
sleep 1
for i in 1 2 3; do
  ip netns exec "c2b${i}" iperf3 -s -D
done
sleep 1

for i in 1 2 3; do
  ip netns exec "c2a${i}" iperf3 -u -c 10.99.${i}.2 -b 9500M -l 8950 -t 10 -O 2 -J > /tmp/c2_path${i}.json 2>/tmp/c2_path${i}.err &
done
wait

echo ""
echo "=== 結果 ==="
for i in 1 2 3; do
  echo "--- 経路${i} ---"
  python3 - "$i" <<'PYEOF'
import json, sys
i = sys.argv[1]
try:
    d = json.load(open(f"/tmp/c2_path{i}.json"))
    s = d["end"]["sum"]
    gbps = s["bytes"] * 8 / s["seconds"] / 1e9
    loss = s.get("lost_percent", -1)
    print(f"スループット: {gbps:.3f} Gbps  損失: {loss:.4f}%")
except Exception as e:
    print(f"[エラー] {e}")
    print("--- 生ログ(先頭5行) ---")
    print(open(f"/tmp/c2_path{i}.json").read()[:500])
PYEOF
done
