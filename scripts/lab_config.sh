#!/bin/bash
# LAB_MODE=veth    → lab_config_veth.sh    (デフォルト)
# LAB_MODE=physical → lab_config_physical.sh (旧: コンテナonスイッチ構成)
# LAB_MODE=c1      → lab_config_c1.sh     (C1物理ファブリック: PC+ASIC 10G, 1トランク共有)
# LAB_MODE=c2      → lab_config_c2.sh     (C2物理ファブリック: PC+ASIC 10G, 3経路完全独立)
_LAB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "${LAB_MODE:-veth}" in
    physical) source "${_LAB_DIR}/lab_config_physical.sh" ;;
    c1)       source "${_LAB_DIR}/lab_config_c1.sh"       ;;
    c2)       source "${_LAB_DIR}/lab_config_c2.sh"       ;;
    *)        source "${_LAB_DIR}/lab_config_veth.sh"     ;;
esac
