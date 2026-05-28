#!/bin/bash
ROUTERS="LER_Ingress_ns LER_Egress_ns CoreRouter1_ns CoreRouter2_ns CoreRouter3_ns"
NODES="$ROUTERS"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB_DIR="$(dirname "$SCRIPT_DIR")"
CONFIGS_DIR="$LAB_DIR/configs"

ns_exists() { ip netns list 2>/dev/null | awk '{print $1}' | grep -qxF "$1"; }
