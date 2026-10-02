#!/usr/bin/env python3
"""無線区間のスループットをリアルタイム表示する。

無線区間は CR1:cr1-lere ─))) ─ LER_Egress:lere-cr1。
その両端のバイトカウンタを読むので、送信量・受信量・無線での損失が同時に分かる。

ODU へ SSH してカウンタを読む方法は、接続ごとの往復時間が測定間隔に乗って
レートを 15% ほど過大評価する。ここではホスト側の /proc を直接読むため、
プロセス生成もSSHもなく、間隔が正確になる。

使い方:
    sudo python3 scripts/radwin_live_monitor.py
    sudo python3 scripts/radwin_live_monitor.py --interval 0.5
    sudo python3 scripts/radwin_live_monitor.py --telemetry 10   # MCS/dBm も併記
    sudo python3 scripts/radwin_live_monitor.py --log-csv <結果フォルダ>/live.csv
        # 毎回のスループットを記録 (plot_radio_timeseries.py が読む)
"""
from __future__ import annotations
import argparse, csv, os, signal, subprocess, sys, time
from pathlib import Path

LOAD_PORT = 5301          # 本番計測 (1000/2000/3000/5201) と衝突しない番号
LOAD_DST = "10.0.2.2"     # LER_Egress:lere-cr1 — 無線区間の対向

# (表示名, netns, インタフェース, 向き)  向き: tx=送出, rx=受信
LINKS = [
    ("無線 送信", "CR1",        "cr1-lere", "tx"),
    ("無線 受信", "LER_Egress", "lere-cr1", "rx"),
    ("CR2 送信",  "LER_Ingress","leri-cr2", "tx"),
    ("CR3 送信",  "LER_Ingress","leri-cr3", "tx"),
]


def ns_pid(ns: str) -> int | None:
    p = subprocess.run(["docker", "inspect", "--format", "{{.State.Pid}}", ns],
                       capture_output=True, text=True)
    try:
        return int(p.stdout.strip())
    except ValueError:
        return None


def read_dev(pid: int) -> dict[str, tuple[int, int]]:
    """/proc/<pid>/net/dev から {iface: (rx_bytes, tx_bytes)}。"""
    out = {}
    try:
        for line in Path(f"/proc/{pid}/net/dev").read_text().splitlines()[2:]:
            name, _, rest = line.partition(":")
            f = rest.split()
            if len(f) >= 9:
                out[name.strip()] = (int(f[0]), int(f[8]))
    except OSError:
        pass
    return out


def current_cr1_bw() -> str:
    """いま HTB に入っている CR1 の整形レート。"""
    p = subprocess.run(["ip", "netns", "exec", "CR1", "tc", "class", "show",
                        "dev", "cr1-lere"], capture_output=True, text=True)
    for line in p.stdout.splitlines():
        if "class htb 1:1 " in line and "rate" in line:
            t = line.split()
            if "ceil" in t:
                return t[t.index("ceil") + 1]
    return "?"


def measurement_running() -> bool:
    """本番計測の iperf3 が動いていれば True。負荷を重ねてはいけない。"""
    p = subprocess.run(["pgrep", "-af", "iperf3"], capture_output=True, text=True)
    return any(f"port {q}" in p.stdout or f"-p {q}" in p.stdout
               for q in ("1000", "2000", "3000"))


# --telemetry 指定時に CSV へ書く列。各無線の親機 (.31 / .33) から見た値。
# tele_time はその値を取得した時刻 (UNIX 秒)。行の time とずれるので、鮮度の確認に使う。
TELE_COLS = ["tele_time",
             "hop1_tx_mcs", "hop1_rx_mcs", "hop1_dbm", "hop1_tx_phy_mbps",
             "hop2_tx_mcs", "hop2_rx_mcs", "hop2_dbm", "hop2_tx_phy_mbps"]


def tele_values(hops: list[dict], t: float) -> list:
    """collect() の結果を TELE_COLS の並びにする。未接続のホップは空欄。"""
    row = [f"{t:.3f}"]
    for i in range(2):
        x = hops[i] if i < len(hops) else {}
        if x.get("connected"):
            row += [x.get("tx_mcs", ""), x.get("rx_mcs", ""), x.get("signal_dbm", ""),
                    x.get("tx_phy_mbps", "")]
        else:
            row += ["", "", "", ""]
    return [("" if v is None else v) for v in row]


def start_load(streams: int) -> list[subprocess.Popen]:
    """無線区間 (CR1 → LER_Egress) に負荷をかける。

    このトラフィックは fwmark を持たないため HTB の分類にかからず、
    整形を受けずに無線の素の実力を流す (htb default が実在しないクラスを
    指しているため未分類は direct queue に落ちる)。
    アンテナ調整の指標としてはこれが望ましい。
    """
    procs = []
    procs.append(subprocess.Popen(
        ["ip", "netns", "exec", "LER_Egress", "iperf3", "-s", "-p", str(LOAD_PORT)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True))
    time.sleep(0.6)
    procs.append(subprocess.Popen(
        ["ip", "netns", "exec", "CR1", "iperf3", "-c", LOAD_DST, "-p", str(LOAD_PORT),
         "-t", "86400", "-P", str(streams)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True))
    return procs


def stop_load(procs: list[subprocess.Popen]) -> None:
    """自分が起動したプロセス群だけを、グループごと確実に終わらせる。"""
    for pr in procs:
        try:
            os.killpg(os.getpgid(pr.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    for pr in procs:
        try:
            pr.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(pr.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass


def bar(v: float, vmax: float, w: int = 28) -> str:
    n = 0 if vmax <= 0 else min(w, int(v / vmax * w))
    return "█" * n + "·" * (w - n)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--telemetry", type=float, default=0,
                    help="N秒ごとにODUのMCS/dBmも取得 (0=取得しない)")
    ap.add_argument("--no-load", action="store_true",
                    help="負荷をかけずに監視だけ行う")
    ap.add_argument("--streams", type=int, default=4, help="負荷のストリーム数")
    ap.add_argument("--log-csv", default=None,
                    help="毎回の値を CSV に記録する (時刻は UNIX 秒。controller.csv と同じ基準)")
    a = ap.parse_args()

    pids = {}
    for _, ns, _, _ in LINKS:
        if ns not in pids:
            pid = ns_pid(ns)
            if pid is None:
                print(f"[ERROR] {ns} が見つかりません。ラボは起動していますか", file=sys.stderr)
                return 1
            pids[ns] = pid

    collect = None
    if a.telemetry > 0:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from radwin_telemetry import collect  # noqa

    # 読めないインタフェースを黙って 0 として扱わない。起動時に必ず確認する。
    missing = []
    for _, ns, ifc, _ in LINKS:
        if ifc not in read_dev(pids[ns]):
            missing.append(f"{ns}:{ifc}")
    if missing:
        print(f"[ERROR] 次のインタフェースが見つかりません: {', '.join(missing)}",
              file=sys.stderr)
        print("        ラボの構成を確認してください "
              "(ip netns exec <ns> ip -br link)", file=sys.stderr)
        return 1

    prev, prev_t = {}, time.monotonic()
    for _, ns, ifc, _ in LINKS:
        prev[(ns, ifc)] = read_dev(pids[ns])[ifc]

    load_procs: list[subprocess.Popen] = []
    load_note = "負荷なし (--no-load)"
    if not a.no_load:
        if measurement_running():
            load_note = "負荷なし — 本番計測が動作中のため自粛"
            print("[WARN] 本番計測の iperf3 を検出しました。負荷はかけません。\n"
                  "       計測中の監視は読み取りのみで安全です。\n")
            time.sleep(2)
        else:
            print(f"無線区間に負荷をかけます "
                  f"(CR1 → {LOAD_DST}:{LOAD_PORT} / {a.streams}ストリーム) ...")
            load_procs = start_load(a.streams)
            load_note = f"負荷あり {a.streams}ストリーム (このツールが生成)"
            time.sleep(1.5)

    log = writer = None
    if a.log_csv:
        path = Path(a.log_csv)
        if path.exists():
            print(f"[ERROR] 既に存在します (上書きしない): {path}", file=sys.stderr)
            stop_load(load_procs)
            return 1
        path.parent.mkdir(parents=True, exist_ok=True)
        log = path.open("w", newline="")
        writer = csv.writer(log)
        writer.writerow(["time", "wireless_tx_gbps", "wireless_rx_gbps", "wireless_loss_pct",
                         "cr2_tx_gbps", "cr3_tx_gbps", "load"] + TELE_COLS)

    tele, tele_at = "", 0.0
    tele_row = [""] * len(TELE_COLS)   # 直近のテレメトリ。取得のない行は前回値を繰り返す
    try:
        while True:
            time.sleep(a.interval)
            now = time.monotonic()
            dt = now - prev_t
            prev_t = now

            vals = {}
            for label, ns, ifc, dirn in LINKS:
                cur = read_dev(pids[ns]).get(ifc, (0, 0))
                old = prev[(ns, ifc)]
                idx = 0 if dirn == "rx" else 1
                vals[label] = (cur[idx] - old[idx]) * 8 / dt / 1e9   # Gbps
                prev[(ns, ifc)] = cur

            if collect and now - tele_at >= a.telemetry:
                try:
                    d = collect()
                    h = d.get("hops", [])
                    tele = "  ".join(
                        f"無線{i+1} MCS{x.get('tx_mcs')}/{x.get('signal_dbm')}dBm"
                        for i, x in enumerate(h) if x.get("connected"))
                    tele += f"   推定容量 {d.get('chain_mbps', 0)/1000:.2f} Gbps"
                    tele_row = tele_values(h, time.time())
                except Exception as e:                       # 取得失敗で監視は止めない
                    tele = f"(テレメトリ取得失敗: {e})"
                    tele_row = [""] * len(TELE_COLS)
                tele_at = now

            tx, rx = vals["無線 送信"], vals["無線 受信"]
            loss = (tx - rx) / tx * 100 if tx > 0.01 else 0.0
            if writer:
                # 時刻は測定区間の終わり。値はその直前 dt 秒の平均レート。
                writer.writerow([f"{time.time():.3f}", f"{tx:.4f}", f"{rx:.4f}", f"{loss:.2f}",
                                 f"{vals['CR2 送信']:.4f}", f"{vals['CR3 送信']:.4f}",
                                 int(bool(load_procs))] + tele_row)
                log.flush()
            vmax = max(9.5, tx, rx)

            print("\033[H\033[J", end="")     # 画面クリア
            print(f"無線区間のリアルタイム監視   間隔 {a.interval}s   "
                  f"HTB整形レート {current_cr1_bw()}")
            print(f"  {load_note}\n")
            print(f"  無線 送信 (cr1-lere)  {tx:6.3f} Gbps  {bar(tx, vmax)}")
            print(f"  無線 受信 (lere-cr1)  {rx:6.3f} Gbps  {bar(rx, vmax)}")
            mark = "  ← 損失大" if loss > 5 else ""
            print(f"  無線での損失          {loss:6.2f} %{mark}\n")
            print(f"  CR2 送信 (有線)       {vals['CR2 送信']:6.3f} Gbps  {bar(vals['CR2 送信'], vmax)}")
            print(f"  CR3 送信 (有線)       {vals['CR3 送信']:6.3f} Gbps  {bar(vals['CR3 送信'], vmax)}")
            if tele:
                print(f"\n  {tele}")
            if max(vals.values()) < 0.005:
                if load_procs:
                    print("\n  !! 負荷をかけているのに通信がありません。")
                    print("     無線リンクが切れているか、経路が壊れています。")
                    print("     確認: sudo bash scripts/diag_class_path.sh")
                else:
                    print("\n  !! トラフィックが流れていません。")
                    print("     --no-load を外すか、別途負荷をかけてください。")
            print("\n  Ctrl+C で終了")
    except KeyboardInterrupt:
        print("\n停止中...")
    finally:
        if log:
            log.close()
            print(f"記録: {a.log_csv}")
        if load_procs:
            stop_load(load_procs)
            print("負荷を停止しました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
