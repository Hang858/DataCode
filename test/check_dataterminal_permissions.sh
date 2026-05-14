#!/usr/bin/env bash
set -u

DT_DB_HOST="${DT_DB_HOST:-192.168.23.204}"
DT_DB_PORT="${DT_DB_PORT:-3306}"
DT_DB_USER="${DT_DB_USER:-root}"
DT_DB_PASS="${DT_DB_PASS:-MyPass123!}"
DT_PERM_DB="${DT_PERM_DB:-permissions}"

PRODUCER="${PRODUCER:-Module/2}"
DATA_TYPE="${DATA_TYPE:-1}"
DATA_SUBTYPE="${DATA_SUBTYPE:-1001}"
TASK_ID="${TASK_ID:-1}"

mysql_base=(
  mysql
  -h"${DT_DB_HOST}"
  -P"${DT_DB_PORT}"
  -u"${DT_DB_USER}"
  -p"${DT_DB_PASS}"
  "${DT_PERM_DB}"
)

echo "DataTerminal permission diagnostics"
echo "db=${DT_DB_USER}@${DT_DB_HOST}:${DT_DB_PORT}/${DT_PERM_DB}"
echo "producer=${PRODUCER} data_type=${DATA_TYPE} data_subtype=${DATA_SUBTYPE} task_id=${TASK_ID}"
echo

"${mysql_base[@]}" -e "
SHOW TABLES;

SELECT 'system_auths' AS section;
SELECT id, system_id, name, auth_key
FROM system_auths
WHERE system_id = '${PRODUCER}';

SELECT 'publish_permissions for producer' AS section;
SELECT id, data_right_id, system_id, data_type, data_subtype, task
FROM publish_permissions
WHERE system_id = '${PRODUCER}'
ORDER BY id;

SELECT 'exact publish permission match' AS section;
SELECT id, data_right_id, system_id, data_type, data_subtype, task
FROM publish_permissions
WHERE system_id = '${PRODUCER}'
  AND data_type = ${DATA_TYPE}
  AND data_subtype = ${DATA_SUBTYPE}
  AND task = ${TASK_ID};

SELECT 'matching subscribe queues' AS section;
SELECT id, data_right_id, system_id, data_type, data_subtype, producer, task
FROM subscribe_permissions
WHERE data_type = ${DATA_TYPE}
  AND data_subtype = ${DATA_SUBTYPE}
  AND producer = '${PRODUCER}'
  AND task = ${TASK_ID}
ORDER BY id;

SELECT 'latest request_permissions for producer' AS section;
SELECT id, system_id, request_type, cookie, timestamp
FROM request_permissions
WHERE system_id = '${PRODUCER}'
ORDER BY id DESC
LIMIT 5;
"
