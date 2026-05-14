#!/usr/bin/env bash
set -u

OS_HOST="${OS_HOST:-192.168.23.204}"
OS_PORT="${OS_PORT:-9200}"
OS_USER="${OS_USER:-admin}"
OS_PASSWORD="${OS_PASSWORD:-MyStrongPass123!}"

MYSQL_HOST="${MYSQL_HOST:-127.0.0.1}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_USER="${MYSQL_USER:-root}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:-MyPass123!}"
MYSQL_DB="${MYSQL_DB:-online}"

OUTPUT="${OUTPUT:-darknet_server_diagnostics.txt}"
OS_BASE="https://${OS_HOST}:${OS_PORT}"
DARKNET_INDEX="${DARKNET_INDEX:-darknet_index}"

run_section() {
  local title="$1"
  shift
  {
    printf '\n===== %s =====\n' "$title"
    printf '$'
    printf ' %q' "$@"
    printf '\n'
  } >> "$OUTPUT"
  "$@" >> "$OUTPUT" 2>&1
  local status=$?
  printf '\n[exit_code=%s]\n' "$status" >> "$OUTPUT"
}

run_os_get() {
  local title="$1"
  local path="$2"
  run_section "$title" curl -k -u "${OS_USER}:${OS_PASSWORD}" "${OS_BASE}${path}"
}

run_os_post() {
  local title="$1"
  local path="$2"
  local body="$3"
  run_section "$title" curl -k -u "${OS_USER}:${OS_PASSWORD}" "${OS_BASE}${path}" -H "Content-Type: application/json" -d "$body"
}

run_mysql() {
  local title="$1"
  local sql="$2"
  run_section "$title" mysql -h"${MYSQL_HOST}" -P"${MYSQL_PORT}" -u"${MYSQL_USER}" -p"${MYSQL_PASSWORD}" "${MYSQL_DB}" -e "$sql"
}

: > "$OUTPUT"
{
  echo "darknet server diagnostics"
  echo "generated_at=$(date '+%Y-%m-%d %H:%M:%S %z')"
  echo "os_base=${OS_BASE}"
  echo "darknet_index=${DARKNET_INDEX}"
  echo "mysql=${MYSQL_USER}@${MYSQL_HOST}:${MYSQL_PORT}/${MYSQL_DB}"
} >> "$OUTPUT"

run_os_get "OpenSearch cluster health" "/_cluster/health?pretty"
run_os_get "OpenSearch darknet cat index" "/_cat/indices/${DARKNET_INDEX}?v"
run_os_get "OpenSearch darknet cat shards" "/_cat/shards/${DARKNET_INDEX}?v"
run_os_get "OpenSearch darknet mapping" "/${DARKNET_INDEX}/_mapping?pretty"
run_os_get "OpenSearch darknet count" "/${DARKNET_INDEX}/_count?pretty"

run_os_post "darknet sample latest timestamp" "/${DARKNET_INDEX}/_search?pretty" '{
  "size": 3,
  "_source": ["id", "original_id", "timestamp", "msg_release_time", "title", "url", "child_file"],
  "sort": [
    {"timestamp": {"order": "desc"}}
  ],
  "query": {"match_all": {}}
}'

run_os_post "darknet id sort probe" "/${DARKNET_INDEX}/_search?pretty" '{
  "size": 3,
  "_source": ["id", "original_id", "timestamp", "msg_release_time", "title", "child_file"],
  "sort": [
    {"id": {"order": "desc", "unmapped_type": "long"}}
  ],
  "query": {"match_all": {}}
}'

run_os_post "darknet original_id existence sample" "/${DARKNET_INDEX}/_search?pretty" '{
  "size": 3,
  "_source": ["id", "original_id", "timestamp", "title"],
  "query": {
    "exists": {"field": "original_id"}
  }
}'

run_mysql "MySQL show related tables" "SHOW TABLES LIKE 'darknet'; SHOW TABLES LIKE 'darknet_id_map'; SHOW TABLES LIKE 'file';"
run_mysql "MySQL desc file" "DESC file;"
run_mysql "MySQL desc darknet if exists" "DESC darknet;"
run_mysql "MySQL darknet counts if exists" "SELECT COUNT(*) AS count, MAX(id) AS max_id FROM darknet;"
run_mysql "MySQL desc darknet_id_map if exists" "DESC darknet_id_map; SELECT COUNT(*) AS count, MAX(id) AS max_id FROM darknet_id_map; SELECT * FROM darknet_id_map ORDER BY id DESC LIMIT 5;"
run_mysql "MySQL file darknet datasource count" "SELECT COUNT(*) AS count, MAX(file_id) AS max_file_id FROM file WHERE datasource = 3;"

run_section "Python dependency check" python3 -c "import importlib.util; mods = ['mysql.connector', 'opensearchpy', 'requests', 'urllib3']; [print(name, 'OK' if importlib.util.find_spec(name) else 'FAIL') for name in mods]"

echo "diagnostics written to ${OUTPUT}"
