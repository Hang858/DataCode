#!/usr/bin/env bash
set -u

DT_DB_HOST="${DT_DB_HOST:-192.168.23.204}"
DT_DB_PORT="${DT_DB_PORT:-3306}"
DT_DB_USER="${DT_DB_USER:-root}"
DT_DB_PASS="${DT_DB_PASS:-MyPass123!}"
DT_PERM_DB="${DT_PERM_DB:-permissions}"

MODULES_CSV="${MODULES_CSV:-Module/2,Module/7,Module/9}"

mysql_base=(
  mysql
  -h"${DT_DB_HOST}"
  -P"${DT_DB_PORT}"
  -u"${DT_DB_USER}"
  -p"${DT_DB_PASS}"
  "${DT_PERM_DB}"
)

echo "DataTerminal module permission diagnostics"
echo "db=${DT_DB_USER}@${DT_DB_HOST}:${DT_DB_PORT}/${DT_PERM_DB}"
echo "modules=${MODULES_CSV}"
echo

"${mysql_base[@]}" -e "
SELECT 'system_auths' AS section;
SELECT id, system_id, name, auth_key
FROM system_auths
WHERE FIND_IN_SET(system_id, '${MODULES_CSV}')
ORDER BY system_id;

SELECT 'publish permissions for modules' AS section;
SELECT id, data_right_id, system_id, data_type, data_subtype, task
FROM publish_permissions
WHERE FIND_IN_SET(system_id, '${MODULES_CSV}')
ORDER BY system_id, data_type, data_subtype, task, data_right_id;

SELECT 'subscribe permissions involving modules as producers' AS section;
SELECT id, data_right_id, system_id AS subscriber, data_type, data_subtype, producer, task
FROM subscribe_permissions
WHERE FIND_IN_SET(producer, '${MODULES_CSV}')
ORDER BY producer, data_type, data_subtype, task, data_right_id, subscriber;

SELECT 'publish permissions with matching write queues' AS section;
SELECT
  p.system_id AS producer,
  p.data_type,
  p.data_subtype,
  p.task AS task_id,
  p.data_right_id AS publish_data_right_id,
  s.data_right_id AS queue_data_right_id,
  s.system_id AS subscriber
FROM publish_permissions p
LEFT JOIN subscribe_permissions s
  ON s.producer = p.system_id
 AND s.data_type = p.data_type
 AND s.data_subtype = p.data_subtype
 AND s.task = p.task
WHERE FIND_IN_SET(p.system_id, '${MODULES_CSV}')
ORDER BY p.system_id, p.data_subtype, p.task, s.data_right_id;

SELECT 'publish permissions without matching write queue' AS section;
SELECT p.id, p.data_right_id, p.system_id, p.data_type, p.data_subtype, p.task
FROM publish_permissions p
LEFT JOIN subscribe_permissions s
  ON s.producer = p.system_id
 AND s.data_type = p.data_type
 AND s.data_subtype = p.data_subtype
 AND s.task = p.task
WHERE FIND_IN_SET(p.system_id, '${MODULES_CSV}')
  AND s.id IS NULL
ORDER BY p.system_id, p.data_subtype, p.task;

SELECT 'latest request permissions' AS section;
SELECT id, system_id, request_type, timestamp
FROM request_permissions
WHERE FIND_IN_SET(system_id, '${MODULES_CSV}')
ORDER BY id DESC
LIMIT 20;
"

echo
echo "Suggested send tests from existing publish permissions:"
"${mysql_base[@]}" -N -e "
SELECT cmd
FROM (
  SELECT DISTINCT
    p.system_id,
    p.data_subtype,
    p.task,
    CONCAT(
      'python3 test_sendworker_publish_modules.py --base-url http://192.168.23.201:8443 --modules ',
      REPLACE(p.system_id, 'Module/', ''),
      ' --subtypes ',
      p.data_subtype,
      ' --task-id ',
      p.task
    ) AS cmd
  FROM publish_permissions p
  WHERE FIND_IN_SET(p.system_id, '${MODULES_CSV}')
) t
ORDER BY system_id, data_subtype, task;
"
