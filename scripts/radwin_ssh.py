#!/usr/bin/env python3
"""ODU にパスワード認証で SSH してコマンドを実行する。

dropbear v2019.78 が公開鍵を受け付けないため (2026-09-18 に確認: 鍵は
$HOME/.ssh/authorized_keys に正しく入っているが Offering した時点で拒否される)、
パスワード認証を pty 経由で自動化する。sshpass のインストールは不要で
Python 標準ライブラリだけで動く。

パスワードは引数に書かず、ファイルから読む (既定 ~/.radwin_pass, chmod 600)。

使い方:
    sudo python3 scripts/radwin_ssh.py <IP> '<コマンド>'
    sudo python3 scripts/radwin_ssh.py 192.168.1.31 'iw dev wlan0 station dump'
"""
from __future__ import annotations
import os
import pty
import select
import signal
import sys

# ODU は CR1 コンテナと同じ L2 にいる。PC から直接は届かないので netns 経由。
NETNS = os.environ.get("RADWIN_NETNS", "CR1")
USER = os.environ.get("RADWIN_USER", "root")


def _pass_file_candidates() -> list[str]:
    """パスワードファイルの探索先。

    sudo 実行時は HOME が /root になるため expanduser("~") だけだと
    ユーザーが作った ~/.radwin_pass を見つけられない (2026-09-18 に遭遇)。
    SUDO_USER のホームを優先し、root のホームも候補に入れる。
    """
    env = os.environ.get("RADWIN_PASS_FILE")
    if env:
        return [env]
    cands = []
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        try:
            import pwd
            cands.append(os.path.join(pwd.getpwnam(sudo_user).pw_dir, ".radwin_pass"))
        except KeyError:
            pass
    cands.append(os.path.expanduser("~/.radwin_pass"))
    # 重複を除いて順序は保つ
    return list(dict.fromkeys(cands))


PASS_FILE = _pass_file_candidates()[0]

SSH_OPTS = [
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    # dropbear は ssh-rsa ホスト鍵しか出さない
    "-o", "HostKeyAlgorithms=+ssh-rsa",
    "-o", "PubkeyAcceptedKeyTypes=+ssh-rsa",
    # 公開鍵は使わない (拒否されるため。試行すると遅くなるだけ)
    "-o", "PubkeyAuthentication=no",
    "-o", "PreferredAuthentications=password",
    "-o", "NumberOfPasswordPrompts=1",
    "-o", "ConnectTimeout=8",
    # 接続後に相手が消えた (無線断など) とき、TCP の再送タイムアウト (数分) を待たずに切る
    "-o", "ServerAliveInterval=2",
    "-o", "ServerAliveCountMax=2",
    "-o", "LogLevel=ERROR",
]


def read_password() -> str:
    cands = _pass_file_candidates()
    for path in cands:
        try:
            with open(path) as f:
                pw = f.read().strip()
            if pw:
                return pw
        except OSError:
            continue
    sys.exit(
        "[NG] パスワードファイルが見つからない。探した場所:\n"
        + "".join(f"        {c}\n" for c in cands)
        + "      作成方法 (sudo を付けずに実行すること):\n"
        f"        printf '%s' '<ODUのパスワード>' > {cands[0]}\n"
        f"        chmod 600 {cands[0]}"
    )


# CR1 コンテナに付ける管理用アドレス。ODU (192.168.1.x) と同じ L2 に居るため、
# これを付けるだけで配線を変えずに ODU へ到達できる。
MGMT_IP = os.environ.get("RADWIN_MGMT_IP", "192.168.1.200/24")
MGMT_DEV = os.environ.get("RADWIN_MGMT_DEV", "cr1-lere")


def ensure_mgmt_ip() -> None:
    """CR1 の cr1-lere に管理用アドレスが無ければ付ける (冪等)。

    これが無いと ODU に届かない。毎回手で足すと付け忘れ事故が起きるので
    接続層で面倒を見る。実験トラフィックへの影響は無い (アドレスが1つ増えるだけ)。
    """
    import subprocess
    show = subprocess.run(
        ["ip", "netns", "exec", NETNS, "ip", "-4", "addr", "show", "dev", MGMT_DEV],
        capture_output=True, text=True)
    if MGMT_IP.split("/")[0] in show.stdout:
        return
    subprocess.run(
        ["ip", "netns", "exec", NETNS, "ip", "addr", "add", MGMT_IP, "dev", MGMT_DEV],
        capture_output=True)


def ssh_run(host: str, command: str, timeout: float = 20.0) -> tuple[int, str]:
    """ODU でコマンドを実行し (終了コード, 出力) を返す。"""
    ensure_mgmt_ip()
    password = read_password()
    argv = ["ip", "netns", "exec", NETNS, "ssh"] + SSH_OPTS + [f"{USER}@{host}", command]
    return _run_pty(argv, password, timeout)


def _run_pty(argv: list[str], password: str, timeout: float) -> tuple[int, str]:
    """pty 経由で実行し、パスワードプロンプトに一度だけ答える。timeout で必ず戻る。"""
    pid, fd = pty.fork()
    if pid == 0:                      # 子プロセス
        os.execvp(argv[0], argv)      # 戻らない

    out = bytearray()
    sent = False
    deadline = __import__("time").monotonic() + timeout
    try:
        while True:
            remain = deadline - __import__("time").monotonic()
            if remain <= 0:
                break
            r, _, _ = select.select([fd], [], [], min(remain, 0.5))
            if fd in r:
                try:
                    chunk = os.read(fd, 65536)
                except OSError:       # 相手が閉じた = 正常終了
                    break
                if not chunk:
                    break
                out += chunk
                # パスワードプロンプトが来たら一度だけ入力する
                if not sent and b"assword" in bytes(out[-200:]):
                    os.write(fd, password.encode() + b"\n")
                    sent = True
            else:
                # 子が終了していれば抜ける
                if os.waitpid(pid, os.WNOHANG)[0] == pid:
                    break
    finally:
        os.close(fd)
    # 時間切れで抜けた場合、子はまだ生きている。以前はここで終了を待ち続けたため、
    # 無線断で ODU が消えると制御ループが 80 秒止まった (2026-09-25 実機)。
    # 必ず止めてから回収する。
    if _still_alive(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        _, status = os.waitpid(pid, 0)
    except ChildProcessError:
        status = 0
    text = out.decode("utf-8", "replace")
    # エコーバックされたプロンプト行を落とす
    lines = [l for l in text.splitlines()
             if "assword" not in l and not l.startswith("Warning: Permanently added")]
    return os.WEXITSTATUS(status) if os.WIFEXITED(status) else 1, "\n".join(lines).strip()


def _still_alive(pid: int) -> bool:
    try:
        return os.waitpid(pid, os.WNOHANG)[0] == 0
    except ChildProcessError:
        return False


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    code, output = ssh_run(sys.argv[1], sys.argv[2])
    print(output)
    sys.exit(code)
