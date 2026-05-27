#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

export DJANGO_DB_HOST="${DJANGO_DB_HOST:-192.168.23.204}"
export DJANGO_DB_PORT="${DJANGO_DB_PORT:-3306}"

echo "[1/4] show migrations"
python3 manage.py showmigrations db_display sessions

echo "[2/4] fake-initial db_display 0001"
if python3 manage.py showmigrations db_display | grep -q '\[ \] 0001_initial'; then
  python3 manage.py migrate db_display 0001 --fake-initial
else
  echo "db_display 0001 already applied, skip"
fi

echo "[3/4] apply db_display migrations"
python3 manage.py migrate db_display

echo "[4/4] apply sessions migrations"
python3 manage.py migrate sessions

echo "done"
