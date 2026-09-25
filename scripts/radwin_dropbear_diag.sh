#!/bin/bash
# dropbear が公開鍵をどこから読むのかを調べる (読み取りのみ)
#   sudo bash scripts/radwin_dropbear_diag.sh [IP]
set -u
T="${1:-192.168.1.31}"; U=root
NS=CR1; DEV=cr1-lere; TMP_IP=192.168.1.200/24
LOGF=/tmp/radwin_dropbear_diag.log

ip netns list | grep -qw "$NS" || { echo "[NG] netns $NS が無い"; exit 1; }
_a=0; ip netns exec "$NS" ip addr show dev "$DEV" | grep -q "${TMP_IP%/*}/" || {
    ip netns exec "$NS" ip addr add "$TMP_IP" dev "$DEV" && _a=1; }
trap '[ "$_a" = "1" ] && ip netns exec "$NS" ip addr del "$TMP_IP" dev "$DEV" 2>/dev/null' EXIT

OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
      -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa
      -o ConnectTimeout=8 -o LogLevel=ERROR)

echo "パスワードを一度聞かれます"
ip netns exec "$NS" ssh "${OPTS[@]}" "$U@$T" '
echo "=== root のホームディレクトリ ==="
echo "  \$HOME = $HOME"
getent passwd root 2>/dev/null || grep "^root:" /etc/passwd

echo ""
echo "=== /root/.ssh の中身 ==="
ls -la /root/.ssh/ 2>/dev/null || echo "  (無い)"
echo "  authorized_keys の中身(先頭40字):"
head -c 40 /root/.ssh/authorized_keys 2>/dev/null; echo ""

echo ""
echo "=== /etc/dropbear の中身 ==="
ls -la /etc/dropbear/ 2>/dev/null || echo "  (無い)"

echo ""
echo "=== dropbear プロセスの起動引数 ==="
ps w 2>/dev/null | grep -i "[d]ropbear"

echo ""
echo "=== dropbear のバージョンと対応 ==="
dropbear -V 2>&1 | head -2
command -v dropbearkey dropbearconvert 2>/dev/null

echo ""
echo "=== ファイルシステムが書き込み可能か(再起動で消えないか) ==="
mount | grep -E " / | /etc | /root " | sed "s/^/  /"

echo ""
echo "=== 公開鍵認証を無効にする設定が無いか ==="
grep -rn "dropbear" /etc/config/ 2>/dev/null | head -10
cat /etc/config/dropbear 2>/dev/null | head -20
' 2>&1 | tee "$LOGF"
