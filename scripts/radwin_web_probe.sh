#!/bin/bash
# ODU の Web 管理画面にラボ内から到達できるかを調べる。
#
# SSH は Linux 内部しか触れず、モジュールパラメータは初期化時にしか
# 読まれないことが判明した。ベンダのファームウェアは独自経路で設定を
# 適用しているはずで、その入口が Web UI である可能性が高い。
# ここから設定できれば、計測スクリプトから自動制御できる。
set -u
NS=CR1
DEV=cr1-lere
MGMT=192.168.1.200/24
ODU=${1:-192.168.1.31}

echo "=== 管理用IPの準備 ==="
ip netns exec "$NS" ip addr show dev "$DEV" | grep -q "192.168.1.200" \
  || ip netns exec "$NS" ip addr add "$MGMT" dev "$DEV" 2>/dev/null
ip netns exec "$NS" ip -br addr show dev "$DEV" | sed 's/^/  /'

echo
echo "=== 疎通 ==="
ip netns exec "$NS" ping -c2 -W2 -q "$ODU" 2>&1 | tail -2 | sed 's/^/  /'

echo
echo "=== 開いているポート ==="
for p in 80 443 8080 8443 23 22; do
  if ip netns exec "$NS" timeout 3 bash -c "</dev/tcp/$ODU/$p" 2>/dev/null; then
    echo "  $p/tcp  開"
  else
    echo "  $p/tcp  閉"
  fi
done

echo
echo "=== HTTP の応答 ==="
for url in "http://$ODU/" "https://$ODU/"; do
  echo "--- $url"
  ip netns exec "$NS" curl -sk -m 6 -D- -o /dev/null "$url" 2>&1 | head -8 | sed 's/^/    /'
done

echo
echo "=== トップページに含まれる手がかり ==="
ip netns exec "$NS" curl -sk -m 8 "http://$ODU/" 2>/dev/null \
  | grep -ioE '(login|user|password|form action="[^"]*"|src="[^"]*\.js"|api|cgi-bin[^"]*)' \
  | sort -u | head -15 | sed 's/^/    /'
