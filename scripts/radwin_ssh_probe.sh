#!/bin/bash
# ODU に SSH でログインし、無線情報を取れるコマンドを探す (読み取りのみ)
#   sudo bash scripts/radwin_ssh_probe.sh [ODUのIP]
#
# dropbear は ssh-rsa ホスト鍵しか出さないため、新しい OpenSSH では
# HostKeyAlgorithms / PubkeyAcceptedKeyTypes に +ssh-rsa が必要。
# パスワード (既定 admin) を一度聞かれる。
set -u
T="${1:-192.168.1.31}"
U=root
NS=CR1; DEV=cr1-lere; TMP_IP=192.168.1.200/24
LOGF="${LOGF:-/tmp/radwin_ssh_probe.log}"

ip netns list | grep -qw "$NS" || { echo "[NG] netns $NS が無い"; exit 1; }
_added=0
ip netns exec "$NS" ip addr show dev "$DEV" | grep -q "${TMP_IP%/*}/" || {
    ip netns exec "$NS" ip addr add "$TMP_IP" dev "$DEV" && _added=1; }
cleanup(){ [ "$_added" = "1" ] && ip netns exec "$NS" ip addr del "$TMP_IP" dev "$DEV" 2>/dev/null; }
trap cleanup EXIT

SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
          -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa
          -o ConnectTimeout=8 -o LogLevel=ERROR)

echo "接続先: $U@$T  (パスワードを一度聞かれます。既定は admin)"
echo "出力は $LOGF にも保存されます"
echo ""

ip netns exec "$NS" ssh "${SSH_OPTS[@]}" "$U@$T" '
echo "=== システム ==="
uname -a 2>/dev/null
cat /etc/*release 2>/dev/null | head -3

echo ""
echo "=== 無線情報を取れそうなコマンド ==="
for c in iw iwinfo wlanconfig qdock wil6210 station_info mwctl radwin_cli cli; do
    p=$(command -v $c 2>/dev/null) && echo "  [あり] $p"
done

echo ""
echo "=== 無線インタフェース ==="
ip -br link 2>/dev/null | head -10

echo ""
echo "=== iw があれば station dump ==="
if command -v iw >/dev/null 2>&1; then
    for w in $(iw dev 2>/dev/null | awk "/Interface/{print \$2}"); do
        echo "  --- $w ---"
        iw dev "$w" station dump 2>/dev/null | grep -iE "Station|signal|tx bitrate|rx bitrate|tx packets|MCS" | head -12
        iw dev "$w" link 2>/dev/null | head -8
    done
fi

echo ""
echo "=== /sys, /proc の無線統計 ==="
ls /sys/class/net/ 2>/dev/null | tr "\n" " "; echo ""
for f in /proc/net/wil6210/* /sys/kernel/debug/ieee80211/*/wil6210/*; do
    [ -e "$f" ] && echo "  [あり] $f"
done 2>/dev/null | head -10

echo ""
echo "=== 設定/状態を持っていそうなファイル ==="
ls /tmp/*.json /var/run/*.json /etc/config 2>/dev/null | head -10
' 2>&1 | tee "$LOGF"
