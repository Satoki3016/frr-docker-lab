#!/bin/bash
<<<<<<< HEAD
ROUTERS="LER_Ingress_ns LER_Egress_ns CoreRouter1_ns CoreRouter2_ns CoreRouter3_ns"
NODES="$ROUTERS"
=======
HOSTS="Tx1 Tx2 Tx3 Rx1 Rx2 Rx3"
ROUTERS="LER_Ingress LER_Egress CoreRouter1 CoreRouter2 CoreRouter3"
NODES="$HOSTS $ROUTERS"
>>>>>>> a871d29236fc25033b139708afa500660335c698

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB_DIR="$(dirname "$SCRIPT_DIR")"
CONFIGS_DIR="$LAB_DIR/configs"

<<<<<<< HEAD
ns_exists() { ip netns list 2>/dev/null | awk '{print $1}' | grep -qxF "$1"; }
=======
# コンテナの PID を取得
get_pid() { docker inspect --format '{{.State.Pid}}' "$1" 2>/dev/null; }
>>>>>>> a871d29236fc25033b139708afa500660335c698
