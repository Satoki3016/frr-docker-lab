#!/bin/bash
# ODU telemetry の取得手段を調べる (読み取りのみ・設定変更なし)
#
#   sudo bash scripts/radwin_telemetry_probe.sh
#
# ODU は 192.168.1.x にいるが PC の enp4s0 は SONiC 管理LAN で塞がっている。
# CR1 コンテナが ODU と同じ L2 セグメント (VLAN211) にいるので、そこに
# 192.168.1.x を一時的に足して到達性を確認する。
set -u

# 出力を必ずファイルにも残す (後から読み返せるように)
LOGF="${LOGF:-/tmp/radwin_telemetry_probe.log}"
if [ -z "${_TEED:-}" ]; then
    export _TEED=1
    exec > >(tee "$LOGF") 2>&1
    echo "(出力は $LOGF にも保存されます)"
    echo ""
fi

NS=CR1
DEV=cr1-lere
TMP_IP=192.168.1.200/24
ODUS=(192.168.1.31 192.168.1.32 192.168.1.33 192.168.1.34)
USER=root
PASS=admin

command -v ip >/dev/null || { echo "[NG] ip コマンドが無い"; exit 1; }
ip netns list | grep -qw "$NS" || { echo "[NG] netns '$NS' が無い。先に frr_all_up.sh を実行すること。"; exit 1; }

echo "=== [1] CR1 コンテナに一時IPを付与 ==="
_added=0
if ip netns exec "$NS" ip addr show dev "$DEV" | grep -q "${TMP_IP%/*}/"; then
    echo "  ${TMP_IP} は設定済み"
else
    if ip netns exec "$NS" ip addr add "$TMP_IP" dev "$DEV" 2>/dev/null; then
        echo "  ${TMP_IP} を ${DEV} に追加した (最後に外す)"
        _added=1
    else
        echo "  [NG] IP を追加できなかった"; exit 1
    fi
fi
cleanup() {
    [ "$_added" = "1" ] && ip netns exec "$NS" ip addr del "$TMP_IP" dev "$DEV" 2>/dev/null \
        && echo "  [ok] 一時IP ${TMP_IP} を削除した"
}
trap cleanup EXIT

echo ""
echo "=== [2] ODU への到達性 ==="
_reach=()
for ip in "${ODUS[@]}"; do
    printf "  %-16s " "$ip"
    if ip netns exec "$NS" ping -c2 -W2 "$ip" >/dev/null 2>&1; then
        echo "到達"; _reach+=("$ip")
    else
        echo "到達不可"
    fi
done
[ ${#_reach[@]} -eq 0 ] && { echo ""; echo "  [NG] どの ODU にも届かない。VLAN211 の配線を確認すること。"; exit 1; }

echo ""
echo "=== [3] 開いているポート (22=SSH / 80=HTTP / 443=HTTPS / 161=SNMP) ==="
for ip in "${_reach[@]}"; do
    printf "  %-16s" "$ip"
    for port in 22 80 443; do
        if ip netns exec "$NS" timeout 2 bash -c "echo > /dev/tcp/$ip/$port" 2>/dev/null; then
            printf "  %s=開" "$port"
        else
            printf "  %s=閉" "$port"
        fi
    done
    echo ""
done

TARGET="${_reach[0]}"
echo ""
echo "=== [4] HTTP の応答を確認 ($TARGET) ==="
ip netns exec "$NS" curl -s -m 5 -o /dev/null -w "  / への応答: HTTP %{http_code} (%{content_type})\n" \
    "http://$TARGET/" 2>/dev/null || echo "  curl が使えない (コンテナに未インストール)"

echo ""
echo "  --- よくある API パスを探索 ---"
for path in api/status api/v1/status status.json api/login cgi-bin/luci ubus; do
    code=$(ip netns exec "$NS" curl -s -m 4 -o /dev/null -w '%{http_code}' "http://$TARGET/$path" 2>/dev/null)
    [ -n "$code" ] && [ "$code" != "000" ] && printf "    /%-16s → HTTP %s\n" "$path" "$code"
done

echo ""
echo "=== [5] SSH の確認 ($TARGET) ==="
ip netns exec "$NS" timeout 5 bash -c "echo > /dev/tcp/$TARGET/22" 2>/dev/null \
    && echo "  ポート22 は開いている。鍵かパスワードでログインを試すこと:" \
    && echo "    sudo ip netns exec $NS ssh -o StrictHostKeyChecking=no ${USER}@${TARGET}" \
    || echo "  ポート22 は閉じている。Web UI の Services タブで SSH Server を有効化する必要がある。"

echo ""
echo "=== まとめ ==="
echo "  到達できた ODU: ${_reach[*]}"
echo "  次の判断:"
echo "    ・HTTP が 200 を返す → Web UI の API を叩いて MCS/Datarate を取得できる可能性"
echo "    ・SSH が開いている   → ログインしてコマンドで取得できる可能性"
echo "    ・どちらも不可       → Web UI の Services タブで SSH か SNMP を有効化する"
