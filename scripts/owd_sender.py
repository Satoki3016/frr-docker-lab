#!/usr/bin/env python3
"""UDP 片道遅延（OWD）プローブ送信
パケット形式: [seq:4B uint32][send_time:8B double] = 12B
--dscp 34=AF41 / 36=AF42 / 38=AF43
"""
import socket
import struct
import time
import argparse

HEADER = struct.Struct("!Id")  # seq(uint32) + timestamp(double) = 12B


def run(dst_ip, dst_port, dscp, interval_s, duration_s, label):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if dscp > 0:
        # DSCP を TOS バイト上位6ビットにセット
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, dscp << 2)
    sock.connect((dst_ip, dst_port))

    t_start = time.perf_counter()
    t_end   = t_start + duration_s
    t_next  = t_start
    seq     = 0

    while True:
        now = time.perf_counter()
        if now >= t_end:
            break
        if now >= t_next:
            seq += 1
            sock.send(HEADER.pack(seq, time.time()))
            t_next += interval_s
        else:
            time.sleep(max(0, t_next - time.perf_counter() - 0.00005))

    sock.close()
    print(f"[{label}] sent {seq} OWD probes", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dst",      required=True,            help="宛先IP")
    ap.add_argument("--port",     type=int, required=True,  help="宛先ポート")
    ap.add_argument("--dscp",     type=int, default=0,      help="DSCP値 (AF41=34, AF42=36, AF43=38)")
    ap.add_argument("--interval", type=float, default=0.02, help="送信間隔(秒) デフォルト0.02=50pps")
    ap.add_argument("--duration", type=float, default=60.0)
    ap.add_argument("--label",    default="OWD-Tx")
    args = ap.parse_args()
    run(args.dst, args.port, args.dscp, args.interval, args.duration, args.label)
