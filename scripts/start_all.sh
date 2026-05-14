#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/inspur/Documents/DataCode}"
WEB_HOST="${WEB_HOST:-0.0.0.0}"
WEB_PORT="${WEB_PORT:-8000}"
LOG_DIR="${LOG_DIR:-${PROJECT_DIR}/logs/startup}"
LOG_RETENTION_DAYS="${LOG_RETENTION_DAYS:-7}"
LOG_CLEANUP_ENABLED="${LOG_CLEANUP_ENABLED:-1}"

mkdir -p "${LOG_DIR}"

cd "${PROJECT_DIR}"

find_pids() {
  local pattern="$1"
  pgrep -af "${pattern}" | awk '{print $1}' || true
}

child_pids_recursive() {
  local parent="$1"
  local children child
  children="$(pgrep -P "${parent}" || true)"
  for child in ${children}; do
    echo "${child}"
    child_pids_recursive "${child}"
  done
}

all_related_pids() {
  {
    find_pids "manage.py runserver ${WEB_HOST}:${WEB_PORT}"
    find_pids "datascratch/run_access_modules.py"
    find_pids "sendworker.runners.module7"
    find_pids "sendworker.runners.module9"
    find_pids "manage_logs.sh"
  } | awk 'NF' | sort -n | uniq
}

all_related_pids_with_children() {
  local pid
  for pid in $(all_related_pids); do
    echo "${pid}"
    child_pids_recursive "${pid}"
  done | awk 'NF' | sort -n | uniq
}

one_line_pids() {
  awk 'NF' | sort -n | uniq | tr '\n' ' ' | xargs
}

print_running() {
  local name="$1"
  local pids="$2"
  if [ -n "${pids}" ]; then
    echo "${name} already running: ${pids}"
    ps -fp ${pids} || true
    return 0
  fi
  return 1
}

cleanup_old_logs() {
  local logs_root="${PROJECT_DIR}/logs"
  if [ "${LOG_CLEANUP_ENABLED}" != "1" ]; then
    echo "log cleanup disabled"
    return
  fi
  if [ ! -d "${logs_root}" ]; then
    return
  fi
  if [ -n "$(all_related_pids)" ]; then
    echo "services already running, skip old log cleanup to avoid deleting active logs"
    return
  fi

  echo "cleaning log files older than ${LOG_RETENTION_DAYS} days under ${logs_root}"
  find "${logs_root}" -type f \
    \( -name "*.log" -o -name "*.log.*" -o -name "*.out" -o -name "*.err" \) \
    -mtime +"${LOG_RETENTION_DAYS}" \
    -print -delete
}

start_web() {
  local pattern="manage.py runserver ${WEB_HOST}:${WEB_PORT}"
  local pids
  pids="$(find_pids "${pattern}")"
  if print_running "web" "${pids}"; then
    return
  fi

  local log_file="${LOG_DIR}/web.log"
  echo "starting web -> ${log_file}"
  nohup python3 -u web/manage.py runserver "${WEB_HOST}:${WEB_PORT}" > "${log_file}" 2>&1 &
  echo "web started pid=$!"
}

start_access_modules() {
  local pattern="datascratch/run_access_modules.py"
  local pids
  pids="$(find_pids "${pattern}")"
  if print_running "access_modules" "${pids}"; then
    return
  fi

  local log_file="${LOG_DIR}/access_modules.log"
  echo "starting access_modules -> ${log_file}"
  nohup python3 -u datascratch/run_access_modules.py > "${log_file}" 2>&1 &
  echo "access_modules started pid=$!"
}

start_log_rotator() {
  local pattern="manage_logs.sh"
  local pids
  pids="$(find_pids "${pattern}")"
  if print_running "log_rotator" "${pids}"; then
    return
  fi

  local log_file="${LOG_DIR}/log_rotator.log"
  echo "starting log_rotator -> ${log_file}"
  nohup bash manage_logs.sh > "${log_file}" 2>&1 &
  echo "log_rotator started pid=$!"
}

cleanup_old_logs
start_web
start_access_modules
start_log_rotator

echo
echo "Current processes:"
WEB_PIDS="$(find_pids "manage.py runserver ${WEB_HOST}:${WEB_PORT}")"
ACCESS_PIDS="$(find_pids "datascratch/run_access_modules.py")"
MODULE_PIDS="$(find_pids "sendworker.runners.module7"; find_pids "sendworker.runners.module9")"
ROTATOR_PIDS="$(find_pids "manage_logs.sh")"
[ -n "${WEB_PIDS}" ] && ps -fp ${WEB_PIDS} || true
[ -n "${ACCESS_PIDS}" ] && ps -fp ${ACCESS_PIDS} || true
[ -n "${MODULE_PIDS}" ] && ps -fp ${MODULE_PIDS} || true
[ -n "${ROTATOR_PIDS}" ] && ps -fp ${ROTATOR_PIDS} || true

echo
echo "Logs:"
echo "  web: ${LOG_DIR}/web.log"
echo "  access launcher: ${LOG_DIR}/access_modules.log"
echo "  access module details: ${PROJECT_DIR}/logs/access_modules/"
echo "  cleanup: delete *.log/*.out/*.err older than ${LOG_RETENTION_DAYS} days when services are not running"
echo "  rotator: ${LOG_DIR}/log_rotator.log"

echo
echo "To stop services:"
ALL_STOP_PIDS="$(all_related_pids_with_children | one_line_pids)"
if [ -n "${ALL_STOP_PIDS}" ]; then
  echo "  kill ${ALL_STOP_PIDS}"
  echo "  If they do not exit:"
  echo "  kill -9 ${ALL_STOP_PIDS}"
else
  echo "  no matching service process found"
fi
