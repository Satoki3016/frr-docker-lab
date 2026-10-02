#!/usr/bin/env python3
"""ODU から無線リンクの状態を取得し、チェーンの実効容量を推定する。

各ホップの親機 (.31 / .33) で `iw dev wlan0 station dump` を実行し、
tx bitrate (PHY レート) / MCS / signal を読み取る。

容量モデル:
    C_chain = min(PHY_hop1, PHY_hop2) × EFFICIENCY
    EFFICIENCY = 0.52
根拠 (2026-09-24 に訂正):
    無線そのものの効率は 0.568 と実測した (MCS 12 で ODU 内蔵 SpeedTest 2624 Mbps、
    prs-link-estimator の currentThroughput 12 回平均 2623 Mbps。PHY 4620 Mbps に対する比)。
    ラボ end-to-end の 2.4 Gbps は ODU の 2.5GbE ポート (実効約 2475 Mbps) で頭打ちした値で、
    無線の効率の根拠にはならない。マニュアルに効率の記載は無い。
    0.52 は 0.568 より保守側の値として残している (低い MCS での効率は未測定のため)。
    効率が 1 を大きく下回るのは TDD (半二重)・MAC オーバーヘッド・ビーム訓練による。

使い方:
    sudo python3 scripts/radwin_telemetry.py          # 人間向け表示
    sudo python3 scripts/radwin_telemetry.py --json   # 機械可読
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from radwin_ssh import ssh_run  # noqa: E402

# 各ホップの親機 (AP 側)。Station 側は dump に出てくる相手なので問い合わせ不要。
HOPS = [
    {"name": "無線1", "ap": "192.168.1.31", "sta": "192.168.1.32", "ch": 1},
    {"name": "無線2", "ap": "192.168.1.33", "sta": "192.168.1.34", "ch": 4},
]
EFFICIENCY = 0.52
CMD = "iw dev wlan0 station dump 2>/dev/null"
# 1台あたりの待ち時間の上限 [s]。正常時の応答は約1秒。無線断で ODU に届かないとき
# 既定の 20 秒を待つと、制御の断の検知が 2台 × 20 秒遅れる。
SSH_TIMEOUT = 6.0

_RE_TX = re.compile(r"tx bitrate:\s*([\d.]+)\s*MBit/s(?:.*?MCS\s*(\d+))?")
_RE_RX = re.compile(r"rx bitrate:\s*([\d.]+)\s*MBit/s(?:.*?MCS\s*(\d+))?")
_RE_SIG = re.compile(r"signal:\s*(-?\d+)\s*dBm")
_RE_STA = re.compile(r"Station\s+([0-9a-f:]{17})")


def parse_dump(text: str) -> dict:
    """iw station dump の出力から必要な値を抜く。未接続なら connected=False。"""
    m_tx, m_rx = _RE_TX.search(text), _RE_RX.search(text)
    m_sig, m_sta = _RE_SIG.search(text), _RE_STA.search(text)
    if not m_tx:
        return {"connected": False, "raw": text[:200]}
    return {
        "connected": True,
        "peer": m_sta.group(1) if m_sta else None,
        "tx_phy_mbps": float(m_tx.group(1)),
        "tx_mcs": int(m_tx.group(2)) if m_tx.group(2) else None,
        "rx_phy_mbps": float(m_rx.group(1)) if m_rx else None,
        "rx_mcs": int(m_rx.group(2)) if m_rx and m_rx.group(2) else None,
        "signal_dbm": int(m_sig.group(1)) if m_sig else None,
    }


def collect() -> dict:
    """全ホップの状態とチェーン容量の推定値を返す。"""
    hops = []
    for h in HOPS:
        code, out = ssh_run(h["ap"], CMD, timeout=SSH_TIMEOUT)
        # 失敗の理由を区別して残す。どちらも「未接続」だが、対処が違う。
        #   ssh_failed … 親機に管理用の通信が届かない (中継・ケーブル・電源、Web UI で ODU が重い)
        #   no_station … 親機には届いたが、相手の局がいない (その区間の無線が切れている)
        if code != 0:
            st = {"connected": False, "error": out[:200], "why": "ssh_failed", "code": code}
        else:
            st = parse_dump(out)
            if not st.get("connected"):
                st["why"] = "no_station"
        st.update(name=h["name"], ap=h["ap"], channel=h["ch"])
        hops.append(st)

    # トラフィックの向きは Tx→Rx なので、各ホップの「送信方向」= AP の tx bitrate。
    up = [h for h in hops if h.get("connected")]
    if len(up) != len(HOPS):
        return {"hops": hops, "chain_mbps": 0.0, "ok": False,
                "reason": "リンクが張れていないホップがある"}

    bottleneck = min(up, key=lambda h: h["tx_phy_mbps"])
    chain = bottleneck["tx_phy_mbps"] * EFFICIENCY
    return {
        "hops": hops,
        "bottleneck": bottleneck["name"],
        "bottleneck_phy_mbps": bottleneck["tx_phy_mbps"],
        "efficiency": EFFICIENCY,
        "chain_mbps": round(chain, 1),
        "ok": True,
    }


if __name__ == "__main__":
    data = collect()
    if "--json" in sys.argv:
        print(json.dumps(data, ensure_ascii=False))
        sys.exit(0 if data["ok"] else 1)

    for h in data["hops"]:
        if h.get("connected"):
            print(f"  {h['name']} (AP {h['ap']}, ch{h['channel']}) : "
                  f"PHY {h['tx_phy_mbps']:.0f}/{h['rx_phy_mbps']:.0f} Mbps  "
                  f"MCS {h['tx_mcs']}/{h['rx_mcs']}  {h['signal_dbm']} dBm  "
                  f"相手 {h['peer']}")
        else:
            why = {"ssh_failed": f"親機 {h['ap']} に SSH で接続できない (終了コード {h.get('code')})。"
                                 "管理用の通信が届いていない: 中継・ケーブル・電源、または Web UI で ODU が重い",
                   "no_station": f"親機 {h['ap']} には接続できたが、相手の局がいない。この区間の無線が切れている"
                   }.get(h.get("why"), "")
            detail = (h.get("error") or h.get("raw") or "").strip()
            print(f"  {h['name']} (AP {h['ap']}) : **未接続** {why}" + (f"\n      詳細: {detail}" if detail else ""))
    print()
    if data["ok"]:
        print(f"  瓶首: {data['bottleneck']} (PHY {data['bottleneck_phy_mbps']:.0f} Mbps)")
        print(f"  チェーン実効容量の推定: {data['chain_mbps']:.0f} Mbps "
              f"(= PHY × {EFFICIENCY})")
        print(f"  → CR1_BW の目安: {int(data['chain_mbps'] * 0.9)}M")
    else:
        print(f"  [NG] {data['reason']}")
    sys.exit(0 if data["ok"] else 1)
