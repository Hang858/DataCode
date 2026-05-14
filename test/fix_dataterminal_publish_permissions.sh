#!/usr/bin/env bash
set -euo pipefail

DT_DB_HOST="${DT_DB_HOST:-192.168.23.204}"
DT_DB_PORT="${DT_DB_PORT:-3306}"
DT_DB_USER="${DT_DB_USER:-root}"
DT_DB_PASS="${DT_DB_PASS:-MyPass123!}"
DT_PERM_DB="${DT_PERM_DB:-permissions}"

SUBSCRIBER="${SUBSCRIBER:-Module/3}"
MODULES="${MODULES:-Module/2 Module/7 Module/9}"
TASK_IDS="${TASK_IDS:-1 107}"

mysql_base=(
  mysql
  -h"${DT_DB_HOST}"
  -P"${DT_DB_PORT}"
  -u"${DT_DB_USER}"
  -p"${DT_DB_PASS}"
  "${DT_PERM_DB}"
)

next_data_right_id_sql="SELECT COALESCE(MAX(data_right_id), 2600) + 1 FROM (SELECT data_right_id FROM publish_permissions UNION ALL SELECT data_right_id FROM subscribe_permissions) x"

run_sql() {
  "${mysql_base[@]}" -N -B -e "$1"
}

ensure_publish_permission() {
  local producer="$1"
  local subtype="$2"
  local task_id="$3"
  local exists
  exists="$(run_sql "SELECT COUNT(*) FROM publish_permissions WHERE system_id='${producer}' AND data_type=1 AND data_subtype=${subtype} AND task=${task_id};")"
  if [[ "${exists}" != "0" ]]; then
    echo "exists publish producer=${producer} subtype=${subtype} task=${task_id}"
    return
  fi

  local data_right_id
  data_right_id="$(run_sql "${next_data_right_id_sql};")"
  run_sql "INSERT INTO publish_permissions (data_right_id, system_id, data_type, data_subtype, task) VALUES (${data_right_id}, '${producer}', 1, ${subtype}, ${task_id});"
  echo "insert publish data_right_id=${data_right_id} producer=${producer} subtype=${subtype} task=${task_id}"
}

ensure_subscribe_permission() {
  local producer="$1"
  local subtype="$2"
  local task_id="$3"
  local exists
  exists="$(run_sql "SELECT COUNT(*) FROM subscribe_permissions WHERE system_id='${SUBSCRIBER}' AND producer='${producer}' AND data_type=1 AND data_subtype=${subtype} AND task=${task_id};")"
  if [[ "${exists}" != "0" ]]; then
    echo "exists subscribe subscriber=${SUBSCRIBER} producer=${producer} subtype=${subtype} task=${task_id}"
    return
  fi

  local data_right_id
  data_right_id="$(run_sql "${next_data_right_id_sql};")"
  run_sql "INSERT INTO subscribe_permissions (data_right_id, system_id, data_type, data_subtype, producer, task) VALUES (${data_right_id}, '${SUBSCRIBER}', 1, ${subtype}, '${producer}', ${task_id});"
  echo "insert subscribe data_right_id=${data_right_id} subscriber=${SUBSCRIBER} producer=${producer} subtype=${subtype} task=${task_id}"
}

echo "Fix DataTerminal publish/subscribe permissions"
echo "db=${DT_DB_USER}@${DT_DB_HOST}:${DT_DB_PORT}/${DT_PERM_DB}"
echo "modules=${MODULES}"
echo "task_ids=${TASK_IDS}"
echo "subscriber=${SUBSCRIBER}"
echo

for module in ${MODULES}; do
  for task_id in ${TASK_IDS}; do
    for subtype in 1001 1002; do
      ensure_publish_permission "${module}" "${subtype}" "${task_id}"
      ensure_subscribe_permission "${module}" "${subtype}" "${task_id}"
    done
  done
done

echo
echo "After updating DB rows, restart DataTerminal so in-memory permission maps reload."
