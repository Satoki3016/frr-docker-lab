#!/usr/bin/env python3
"""
OMNeT++ UdpBasicApp の再現
  messageLength = 1400 bytes
  sendInterval  = 1ms  (= 1000 pps = ~11.2 Mbps)
  startTime     = 1s
  stopTime      = 59s
"""
import socket
import time
import argparse
import sys

def send(dst_ip, dst_port, msg_len, interval_s, duration_s, label):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    payload = b'X' * msg_len

    print(f"[{label}] sending to {dst_ip}:{dst_port} "
          f"{msg_len}B/{interval_s*1000:.1f}ms for {duration_s}s", flush=True)

    sent = 0
    t_start = time.perf_counter()
    t_end   = t_start + duration_s
    t_next  = t_start

    while True:
        now = time.perf_counter()
        if now >= t_end:
            break
        if now >= t_next:
            sock.sendto(payload, (dst_ip, dst_port))
            sent += 1
            t_next += interval_s
        else:
            # busy-wait（sleep だと精度が落ちる）
            time.sleep(max(0, t_next - time.perf_counter() - 0.0001))

    elapsed = time.perf_counter() - t_start
    mbps = sent * msg_len * 8 / elapsed / 1e6
    print(f"[{label}] sent {sent} pkts in {elapsed:.1f}s = {mbps:.2f} Mbps", flush=True)
    sock.close()

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dst",      required=True,         help="宛先IPアドレス")
    ap.add_argument("--port",     type=int, required=True, help="宛先ポート")
    ap.add_argument("--len",      type=int, default=1400,  help="パケット長(bytes)")
    ap.add_argument("--interval", type=float, default=0.001, help="送信間隔(秒)")
    ap.add_argument("--duration", type=float, default=58.0,  help="送信時間(秒)")
    ap.add_argument("--label",    default="Tx",            help="ラベル名")
    args = ap.parse_args()

    send(args.dst, args.port, args.len, args.interval, args.duration, args.label)
