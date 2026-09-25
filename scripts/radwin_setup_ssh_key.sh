#!/bin/bash
# ODU 4台に SSH 公開鍵を登録し、パスワードなしでログインできるようにする。
# 制御ループ (radwin_wcmp_controller.sh) が無人で telemetry を取るために必要。
#
#   sudo bash scripts/radwin_setup_ssh_key.sh
#
# 各ODUで1回ずつパスワードを聞かれる。登録済みならスキップする。
#
# 注意点 (2026-09-18 に踏んだ):
#   ・TerraNet の root はホームが /root ではなく "/" (/etc/passwd の6列目)。
#     dropbear は $HOME/.ssh/authorized_keys を読むので決め打ちしない。
#   ・鍵の内容を echo でリモートに渡すと入れ子のクォートで壊れる。
#     必ず標準入力でファイルごと渡し、登録後に内容を検証する。
set -u
KEY="${KEY:-/home/kannolab/.ssh/lab_key}"
PUB="${KEY}.pub"
U=root
ODUS=(192.168.1.31 192.168.1.32 192.168.1.33 192.168.1.34)
NS=CR1; DEV=cr1-lere; TMP_IP=192.168.1.200/24
LOGF="${LOGF:-/tmp/radwin_setup_ssh_key.log}"
if [ -z "${_TEED:-}" ]; then export _TEED=1; exec > >(tee "$LOGF") 2>&1; fi

[ -f "$PUB" ] || { echo "[NG] 公開鍵が無い: $PUB"; exit 1; }
ip netns list | grep -qw "$NS" || { echo "[NG] netns $NS が無い。先に frr_all_up.sh を実行すること。"; exit 1; }

_added=0
ip netns exec "$NS" ip addr show dev "$DEV" | grep -q "${TMP_IP%/*}/" || {
    ip netns exec "$NS" ip addr add "$TMP_IP" dev "$DEV" && _added=1; }
trap '[ "$_added" = "1" ] && ip netns exec "$NS" ip addr del "$TMP_IP" dev "$DEV" 2>/dev/null' EXIT

# dropbear は ssh-rsa ホスト鍵しか出さないため +ssh-rsa が必要
OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
      -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa
      -o ConnectTimeout=8 -o LogLevel=ERROR)

LOCAL_FP=$(ssh-keygen -lf "$PUB" | awk '{print $2}')
echo "登録する鍵: $LOCAL_FP"
echo ""

for ip in "${ODUS[@]}"; do
    echo "=== $ip ==="
    if ip netns exec "$NS" ssh "${OPTS[@]}" -i "$KEY" -o BatchMode=yes "$U@$ip" true 2>/dev/null; then
        echo "  [skip] 既に鍵でログインできる"
        continue
    fi

    echo "  パスワードを入力してください:"
    # 鍵は標準入力でそのまま渡す (echo だとクォートで壊れる)
    ip netns exec "$NS" ssh "${OPTS[@]}" "$U@$ip" '
        AK="$HOME/.ssh/authorized_keys"
        mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
        cat >> "$AK"
        # 重複行を除去
        sort -u "$AK" -o "$AK" 2>/dev/null || true
        chmod 600 "$AK"
        echo "    書き込み先: $AK  ($(wc -l < "$AK") 行)"
        echo "    指紋:"
        while read -r l; do
            [ -n "$l" ] && echo "$l" > /tmp/_k.pub && dropbearkey -y -f /dev/null 2>/dev/null
        done < "$AK" 2>/dev/null || true
        echo "    内容(先頭60字): $(head -c 60 "$AK")"
    ' < "$PUB" || { echo "  [NG] 登録に失敗"; continue; }

    if ip netns exec "$NS" ssh "${OPTS[@]}" -i "$KEY" -o BatchMode=yes "$U@$ip" true 2>/dev/null; then
        echo "  [ok] 鍵でのログインを確認"
    else
        echo "  [NG] まだ鍵で入れない"
        echo "       確認: sudo bash scripts/radwin_ssh_authdiag.sh $ip"
    fi
done

echo ""
echo "=== 動作確認: 全ODUから telemetry を取得 ==="
for ip in "${ODUS[@]}"; do
    printf "  %-16s " "$ip"
    out=$(ip netns exec "$NS" ssh "${OPTS[@]}" -i "$KEY" -o BatchMode=yes "$U@$ip" \
          'iw dev wlan0 station dump 2>/dev/null | grep -E "tx bitrate|signal:" | tr "\n" " "' 2>/dev/null)
    [ -n "$out" ] && echo "$out" || echo "(取得できず)"
done
