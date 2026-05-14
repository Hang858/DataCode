#!/usr/bin/env bash
set -euo pipefail

BOOTSTRAP="${BOOTSTRAP:-192.168.23.204:9092}"
GROUP="${GROUP:-Module/7}"
TOPIC="${TOPIC:-Module_7}"
KAFKA_HOME="${KAFKA_HOME:-/home/inspur/kafka}"

KCG="${KAFKA_HOME}/bin/kafka-consumer-groups.sh"
if [ ! -x "${KCG}" ]; then
  KCG="$(command -v kafka-consumer-groups.sh || true)"
fi
if [ -z "${KCG}" ] || [ ! -x "${KCG}" ]; then
  echo "kafka-consumer-groups.sh not found"
  exit 1
fi

echo "Before reset:"
"${KCG}" --bootstrap-server "${BOOTSTRAP}" --describe --group "${GROUP}" || true

cat <<EOF

To reset this group safely:
1. Stop DataTerminal first. The group must have no active members.
2. Run this script again with CONFIRM=1.

Current target:
  bootstrap=${BOOTSTRAP}
  group=${GROUP}
  topic=${TOPIC}
EOF

if [ "${CONFIRM:-0}" != "1" ]; then
  exit 0
fi

echo
echo "Resetting offset to latest..."
"${KCG}" \
  --bootstrap-server "${BOOTSTRAP}" \
  --group "${GROUP}" \
  --topic "${TOPIC}" \
  --reset-offsets \
  --to-latest \
  --execute

echo
echo "After reset:"
"${KCG}" --bootstrap-server "${BOOTSTRAP}" --describe --group "${GROUP}" || true
