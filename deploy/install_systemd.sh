#!/usr/bin/env bash
set -euo pipefail
UNIT_NAME=polymarket-arb.service
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
sudo cp "${SCRIPT_DIR}/polymarket-arb.service" "/etc/systemd/system/${UNIT_NAME}"
sudo systemctl daemon-reload
sudo systemctl enable "${UNIT_NAME}"
sudo systemctl restart "${UNIT_NAME}"
sudo systemctl --no-pager status "${UNIT_NAME}" || true
