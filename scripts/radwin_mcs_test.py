#!/usr/bin/env python3
"""PRS_MAX_MCS が実行中に効くかを確かめる。

モジュールパラメータは書き込めても初期化時にしか読まれない場合がある。
実際に MCS が変わるかを station dump で確認する。

既定は読み取りのみ。--apply を付けたときだけ書き込む。
書き込んだ場合は、異常終了しても必ず元の値へ戻す。

    sudo python3 scripts/radwin_mcs_test.py              # 現状確認のみ
    sudo python3 scripts/radwin_mcs_test.py --apply 9    # MCS 9 に制限して確認
"""
from __future__ import annotations
import argparse, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from radwin_ssh import ssh_run  # noqa: E402

AP = "192.168.1.31"
PDIR = "/sys/module/prs_falcon/parameters"
PARAM = f"{PDIR}/PRS_MAX_MCS"      # --param で切り替える


def read_mcs() -> tuple[str, str]:
    _, out = ssh_run(AP, "iw dev wlan0 station dump 2>/dev/null "
                         "| grep -E 'tx bitrate|signal:'", timeout=20.0)
    rate = re.search(r"tx bitrate:\s*([\d.]+)\s*MBit/s(?:.*?MCS\s*(\d+))?", out or "")
    sig = re.search(r"signal:\s*(-?\d+)", out or "")
    return (f"{rate.group(1)} Mbps / MCS {rate.group(2)}" if rate else "(取得失敗)",
            f"{sig.group(1)} dBm" if sig else "?")


def set_param_path(name: str) -> None:
    global PARAM
    PARAM = f"{PDIR}/{name}"


def read_param() -> str:
    _, out = ssh_run(AP, f"cat {PARAM}", timeout=15.0)
    return (out or "").strip()


def write_param(v: str) -> bool:
    code, out = ssh_run(AP, f"echo {v} > {PARAM} && cat {PARAM}", timeout=15.0)
    ok = (out or "").strip() == str(v)
    if not ok:
        print(f"    [NG] 書き込み結果が一致しません: 期待 {v} / 実際 {out!r}")
    return ok


def show(label: str) -> None:
    rate, sig = read_mcs()
    name = PARAM.rsplit("/", 1)[-1]
    print(f"  {label:20s} {name}={read_param():4s}  {rate:24s} {sig}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--param", default="PRS_MAX_MCS",
                    help="対象パラメータ名 (既定: PRS_MAX_MCS)")
    ap.add_argument("--apply", type=int, default=None,
                    help="この MCS に制限して効果を確認する (終了時に必ず復元)")
    ap.add_argument("--wait", type=float, default=8.0,
                    help="書き込み後にレート適応が追従するまでの待ち時間")
    a = ap.parse_args()
    set_param_path(a.param)

    print("=" * 68)
    print(f"{a.param} の実効性確認  (AP {AP})")
    print("=" * 68)
    _, cfg = ssh_run(AP, "ls -la /etc/config/peraso/ 2>&1 | head -12", timeout=15.0)
    print("\n/etc/config/peraso の中身:")
    for l in (cfg or "").splitlines()[:12]:
        print(f"    {l}")

    print("\n現在の状態:")
    original = read_param()
    show("開始時")

    if a.apply is None:
        print("\n書き込み試験を行うには --apply <MCS> を付けてください")
        print("  例: sudo python3 scripts/radwin_mcs_test.py --apply 9")
        return 0

    print(f"\n書き込み試験: {a.param} = {a.apply}  (元の値 {original} は終了時に復元)")
    try:
        if not write_param(str(a.apply)):
            return 1
        for i in range(3):
            time.sleep(a.wait / 3)
            show(f"適用後 {(i+1)*a.wait/3:.0f}s")
    finally:
        print(f"\n復元中 ({a.param} = {original}) ...")
        write_param(original)
        time.sleep(a.wait / 2)
        show("復元後")

    print("\n" + "=" * 68)
    print("判定:")
    print("  適用後に MCS または受信電力が変化 → 実行中の制御が可能")
    print("  どちらも変わらない               → 初期化時のみ有効。動的操作には使えない")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
