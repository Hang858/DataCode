#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://192.168.23.201:8443}"
MODULE="${MODULE:-7}"
TIMEOUT="${TIMEOUT:-10}"
INTERVAL="${INTERVAL:-1}"
MAX_ROUNDS="${MAX_ROUNDS:-0}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python3 -u "${SCRIPT_DIR}/test_dataterminal_recv_command.py" \
  --base-url "${BASE_URL}" \
  --module "${MODULE}" \
  --timeout "${TIMEOUT}" \
  --loop \
  --interval "${INTERVAL}" \
  --max-rounds "${MAX_ROUNDS}"
