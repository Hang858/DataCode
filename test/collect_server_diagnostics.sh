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

OUTPUT="${OUTPUT:-server_diagnostics.txt}"
OS_BASE="https://${OS_HOST}:${OS_PORT}"

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
  echo "server diagnostics"
  echo "generated_at=$(date '+%Y-%m-%d %H:%M:%S %z')"
  echo "os_base=${OS_BASE}"
  echo "mysql=${MYSQL_USER}@${MYSQL_HOST}:${MYSQL_PORT}/${MYSQL_DB}"
} >> "$OUTPUT"

run_os_get "OpenSearch cluster health" "/_cluster/health?pretty"
run_os_get "OpenSearch nodes" "/_cat/nodes?v"
run_os_get "OpenSearch plugins" "/_cat/plugins?v"
run_os_get "telegram_index cat indices" "/_cat/indices/telegram_index?v"
run_os_get "telegram_index cat shards" "/_cat/shards/telegram_index?v"
run_os_get "telegram_index mapping" "/telegram_index/_mapping?pretty"

run_os_post "telegram_index max id sample" "/telegram_index/_search?pretty" '{
  "size": 1,
  "_source": ["id", "original_id", "message_date", "message_time", "timestamp", "child_file"],
  "sort": [
    {"id": {"order": "desc", "unmapped_type": "long"}}
  ],
  "query": {"match_all": {}}
}'

run_os_post "telegram_index first sample without sort" "/telegram_index/_search?pretty" '{
  "size": 1,
  "_source": ["id", "original_id", "message_date", "message_time", "timestamp", "child_file"],
  "query": {"match_all": {}}
}'

run_mysql "MySQL show telegram_id_map" "SHOW TABLES LIKE 'telegram_id_map';"
run_mysql "MySQL show file" "SHOW TABLES LIKE 'file';"
run_mysql "MySQL desc file" "DESC file;"
run_mysql "MySQL desc telegram_id_map and counts" "DESC telegram_id_map; SELECT COUNT(*) AS count FROM telegram_id_map; SELECT MAX(id) AS max_id FROM telegram_id_map;"

run_section "Python dependency check" python3 -c "import importlib.util; mods = ['mysql.connector', 'opensearchpy', 'requests', 'urllib3']; [print(name, 'OK' if importlib.util.find_spec(name) else 'FAIL') for name in mods]"

echo "diagnostics written to ${OUTPUT}"
