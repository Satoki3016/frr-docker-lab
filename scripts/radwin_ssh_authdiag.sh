#!/bin/bash
# 鍵認証が失敗する理由を SSH の詳細ログで特定する
#   sudo bash scripts/radwin_ssh_authdiag.sh [IP]
set -u
T="${1:-192.168.1.31}"; U=root; KEY=/home/kannolab/.ssh/lab_key
NS=CR1; DEV=cr1-lere; TMP_IP=192.168.1.200/24
LOGF=/tmp/radwin_ssh_authdiag.log

_a=0; ip netns exec "$NS" ip addr show dev "$DEV" | grep -q "${TMP_IP%/*}/" || {
    ip netns exec "$NS" ip addr add "$TMP_IP" dev "$DEV" && _a=1; }
trap '[ "$_a" = "1" ] && ip netns exec "$NS" ip addr del "$TMP_IP" dev "$DEV" 2>/dev/null' EXIT

{
echo "=== 鍵認証の詳細ログ ($T) ==="
ip netns exec "$NS" ssh -vv \
    -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o HostKeyAlgorithms=+ssh-rsa \
    -o PubkeyAcceptedKeyTypes=+ssh-rsa \
    -o PubkeyAuthentication=yes -o PasswordAuthentication=no \
    -o PreferredAuthentications=publickey \
    -o BatchMode=yes -o ConnectTimeout=8 \
    -i "$KEY" "$U@$T" true 2>&1 \
  | grep -iE "offer|authentications that can continue|send_pubkey|signing|Authenticat|no mutual|algorithm|denied|Permission|banner|debug1: Trying" \
  | sed 's/^/  /'

echo ""
echo "=== 署名アルゴリズムを ssh-rsa(SHA-1) に固定して再試行 ==="
ip netns exec "$NS" ssh -v \
    -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o HostKeyAlgorithms=ssh-rsa \
    -o PubkeyAcceptedKeyTypes=ssh-rsa \
    -o PubkeyAuthentication=yes -o PasswordAuthentication=no \
    -o PreferredAuthentications=publickey \
    -o BatchMode=yes -o ConnectTimeout=8 \
    -i "$KEY" "$U@$T" 'echo "  [成功] 鍵で入れた"; iw dev wlan0 station dump 2>/dev/null | grep -E "tx bitrate|signal:"' 2>&1 \
  | grep -vE "^debug1: (Reading|Connecting|identity file|Local version|Remote protocol|compat_banner|Authenticating|SSH2_MSG|kex|rekey|Host .* is known|Will attempt|Offering|Server accepts|Skipping|Trying private|Next authentication|No more)" \
  | sed 's/^/  /' | head -20
} 2>&1 | tee "$LOGF"
