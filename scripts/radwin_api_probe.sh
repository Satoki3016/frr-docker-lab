#!/bin/bash
# ODU の HTTP/HTTPS API 構造を調べる (読み取りのみ)
#   sudo bash scripts/radwin_api_probe.sh
set -u
LOGF="${LOGF:-/tmp/radwin_api_probe.log}"
if [ -z "${_TEED:-}" ]; then export _TEED=1; exec > >(tee "$LOGF") 2>&1; echo "(出力は $LOGF にも保存)"; echo ""; fi

NS=CR1; DEV=cr1-lere; TMP_IP=192.168.1.200/24
T=192.168.1.31; U=root; P=admin
CJ=/tmp/radwin_cookies.txt

ip netns list | grep -qw "$NS" || { echo "[NG] netns $NS が無い"; exit 1; }
_added=0
ip netns exec "$NS" ip addr show dev "$DEV" | grep -q "${TMP_IP%/*}/" || {
    ip netns exec "$NS" ip addr add "$TMP_IP" dev "$DEV" && _added=1; }
cleanup(){ [ "$_added" = "1" ] && ip netns exec "$NS" ip addr del "$TMP_IP" dev "$DEV" 2>/dev/null; rm -f "$CJ"; }
trap cleanup EXIT

nsx() { ip netns exec "$NS" "$@"; }

echo "=== [1] HTTP 302 のリダイレクト先 ==="
nsx curl -s -I -m 5 "http://$T/" 2>/dev/null | grep -iE "^(HTTP|location|server)" | sed 's/^/  /'

echo ""
echo "=== [2] HTTPS のトップページ ==="
nsx curl -sk -m 8 -o /tmp/_root.html -w "  HTTP %{http_code}  type=%{content_type}  size=%{size_download}\n" \
    "https://$T/" 2>/dev/null
echo "  --- HTML から読み取れる手がかり (script/api の記述) ---"
grep -oE '(src|href)="[^"]{3,60}"' /tmp/_root.html 2>/dev/null | sort -u | head -12 | sed 's/^/    /'
grep -oiE '/(api|rpc|cgi[^"]*)[a-z0-9/_.-]*' /tmp/_root.html 2>/dev/null | sort -u | head -10 | sed 's/^/    /'

echo ""
echo "=== [3] ログインを試す (HTTPS) ==="
for ep in api/login login api/auth api/v1/login; do
    for body in "{\"username\":\"$U\",\"password\":\"$P\"}" "username=$U&password=$P"; do
        ct="application/json"; [[ "$body" == *"="* ]] && ct="application/x-www-form-urlencoded"
        code=$(nsx curl -sk -m 6 -c "$CJ" -o /tmp/_login.out -w '%{http_code}' \
               -X POST -H "Content-Type: $ct" -d "$body" "https://$T/$ep" 2>/dev/null)
        if [ "$code" = "200" ] || [ "$code" = "201" ]; then
            echo "  [成功候補] POST /$ep ($ct) → HTTP $code"
            head -c 300 /tmp/_login.out | tr -d '\0' | sed 's/^/      /'; echo ""
            [ -s "$CJ" ] && { echo "      Cookie:"; grep -v '^#' "$CJ" | awk '{print "        "$6"="substr($7,1,20)}'; }
        elif [ "$code" != "000" ] && [ "$code" != "404" ]; then
            printf "  POST /%-14s (%-33s) → HTTP %s\n" "$ep" "$ct" "$code"
        fi
    done
done

echo ""
echo "=== [4] ログイン後に status 系を取得 ==="
for ep in api/status api/wireless api/v1/status status api/dashboard api/system; do
    code=$(nsx curl -sk -m 6 -b "$CJ" -o /tmp/_s.out -w '%{http_code}' "https://$T/$ep" 2>/dev/null)
    if [ "$code" = "200" ]; then
        echo "  [取得成功] GET /$ep"
        head -c 400 /tmp/_s.out | tr -d '\0' | sed 's/^/      /'; echo ""
    elif [ "$code" != "000" ] && [ "$code" != "404" ]; then
        printf "  GET /%-16s → HTTP %s\n" "$ep" "$code"
    fi
done

echo ""
echo "=== [5] SSH のバナーと認証方式 ==="
nsx timeout 5 bash -c "exec 3<>/dev/tcp/$T/22; head -c 80 <&3" 2>/dev/null | tr -d '\0' | sed 's/^/  バナー: /'
echo ""
nsx ssh -o StrictHostKeyChecking=no -o BatchMode=yes -o ConnectTimeout=5 "$U@$T" true 2>&1 \
    | head -3 | sed 's/^/  /'
