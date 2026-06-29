#!/usr/bin/env python3
"""UDP 片道遅延（OWD）プローブ受信
ログ形式: [recv_unix_time] seq=N owd=X.XXX ms
"""
import socket
import struct
import time
import argparse

HEADER = struct.Struct("!Id")  # seq(uint32) + timestamp(double) = 12B


def run(port, duration_s, out_path, label):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", port))
    sock.settimeout(0.5)

    deadline = time.perf_counter() + duration_s + 3
    count = 0

    with open(out_path, "w", buffering=1) as f:
        f.write(f"# OWD receiver: {label}  port={port}\n")
        while time.perf_counter() < deadline:
            try:
                data, _ = sock.recvfrom(1500)
                recv_time = time.time()
                if len(data) < HEADER.size:
                    continue
                seq, send_time = HEADER.unpack_from(data)
                owd_ms = (recv_time - send_time) * 1000
                f.write(f"[{recv_time:.6f}] seq={seq} owd={owd_ms:.3f} ms\n")
                count += 1
            except socket.timeout:
                continue

    sock.close()
    print(f"[{label}] received {count} OWD probes", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port",     type=int, required=True)
    ap.add_argument("--duration", type=float, default=60.0)
    ap.add_argument("--out",      required=True)
    ap.add_argument("--label",    default="OWD-Rx")
    args = ap.parse_args()
    run(args.port, args.duration, args.out, args.label)
