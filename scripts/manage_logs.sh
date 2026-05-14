#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/inspur/Documents/DataCode}"
LOG_ROOT="${LOG_ROOT:-${PROJECT_DIR}/logs}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
MAX_LOG_SIZE_MB="${MAX_LOG_SIZE_MB:-100}"
CHECK_INTERVAL_SECONDS="${CHECK_INTERVAL_SECONDS:-3600}"

rotate_once() {
  local max_size_bytes=$((MAX_LOG_SIZE_MB * 1024 * 1024))
  local ts
  ts="$(date +%Y%m%d_%H%M%S)"

  if [ ! -d "${LOG_ROOT}" ]; then
    mkdir -p "${LOG_ROOT}"
  fi

  find "${LOG_ROOT}" -type f -name "*.log" -size +"${max_size_bytes}"c -print0 |
    while IFS= read -r -d '' log_file; do
      local rotated="${log_file}.${ts}"
      cp "${log_file}" "${rotated}"
      : > "${log_file}"
      gzip -f "${rotated}"
      echo "rotated ${log_file} -> ${rotated}.gz"
    done

  find "${LOG_ROOT}" -type f \
    \( -name "*.log.*" -o -name "*.out.*" -o -name "*.err.*" -o -name "*.gz" \) \
    -mtime +"${RETENTION_DAYS}" \
    -print -delete
}

echo "log rotator started"
echo "  root: ${LOG_ROOT}"
echo "  max size: ${MAX_LOG_SIZE_MB}MB"
echo "  retention: ${RETENTION_DAYS} days"
echo "  interval: ${CHECK_INTERVAL_SECONDS}s"

while true; do
  rotate_once
  sleep "${CHECK_INTERVAL_SECONDS}"
done
