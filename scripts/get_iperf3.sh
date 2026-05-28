#!/bin/bash
# iperf3 (Debian 11対応版) をスイッチに転送するスクリプト
# 実行: bash scripts/get_iperf3.sh <スイッチIP> [ユーザー名]
#
# 例: bash scripts/get_iperf3.sh 192.168.128.33 kannolab

set -e

SWITCH_IP="${1:-192.168.128.33}"
SWITCH_USER="${2:-kannolab}"
WORK_DIR="/tmp/iperf3_deb11"
INNER_SCRIPT="/tmp/iperf3_install_inner.sh"

echo "=== iperf3 取得スクリプト (Debian 11対応版) ==="
echo "  転送先: ${SWITCH_USER}@${SWITCH_IP}:~/bin/"
echo ""

# ----------------------------------------------------------------
# 1. Docker で Debian 11 コンテナからiperf3を取得
# ----------------------------------------------------------------
echo "[1/3] Debian 11 コンテナから iperf3 を取得..."

mkdir -p "$WORK_DIR"

# コンテナ内で実行するスクリプトを作成
cat > "$INNER_SCRIPT" << 'INNER_EOF'
#!/bin/sh
set -e
apt-get update -qq
apt-get install -y -qq iperf3
cp /usr/bin/iperf3 /out/
cp /usr/lib/x86_64-linux-gnu/libiperf.so.0 /out/
# libsctp は任意 (存在する場合のみコピー)
[ -f /usr/lib/x86_64-linux-gnu/libsctp.so.1 ] && cp /usr/lib/x86_64-linux-gnu/libsctp.so.1 /out/ || true
echo "  コピー完了"
INNER_EOF

sudo docker run --rm \
    -v "${WORK_DIR}:/out" \
    -v "${INNER_SCRIPT}:/install.sh" \
    debian:11 \
    sh /install.sh

echo "  取得ファイル:"
ls -lh "$WORK_DIR/"

# ----------------------------------------------------------------
# 2. スイッチへ転送
# ----------------------------------------------------------------
echo ""
echo "[2/3] スイッチへ転送..."

ssh "${SWITCH_USER}@${SWITCH_IP}" "mkdir -p ~/bin"

for f in "$WORK_DIR"/*; do
    scp "$f" "${SWITCH_USER}@${SWITCH_IP}:~/bin/"
    echo "  転送完了: $(basename $f)"
done

# ----------------------------------------------------------------
# 3. スイッチ側で動作確認
# ----------------------------------------------------------------
echo ""
echo "[3/3] スイッチ側で動作確認..."

ssh "${SWITCH_USER}@${SWITCH_IP}" \
    "LD_LIBRARY_PATH=~/bin ~/bin/iperf3 --version && echo '  [OK] iperf3 動作確認完了'"

echo ""
echo "=== 完了 ==="
echo "スイッチ上での使い方:"
echo "  export LD_LIBRARY_PATH=~/bin"
echo "  ~/bin/iperf3 -s -p 1000 &"
