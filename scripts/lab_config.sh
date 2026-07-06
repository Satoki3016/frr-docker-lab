#!/bin/bash
# LAB_MODE=veth    → lab_config_veth.sh    (デフォルト)
# LAB_MODE=physical → lab_config_physical.sh
_LAB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "${LAB_MODE:-veth}" in
    physical) source "${_LAB_DIR}/lab_config_physical.sh" ;;
    *)        source "${_LAB_DIR}/lab_config_veth.sh"     ;;
esac
