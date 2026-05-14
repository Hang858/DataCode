#!/usr/bin/env bash
set -u

TOPIC="${TOPIC:-Module_7}"
GROUP="${GROUP:-Module/7}"
BOOTSTRAP="${BOOTSTRAP:-192.168.23.204:9092}"

echo "Diagnose consumers for topic=${TOPIC} group=${GROUP}"
echo "bootstrap=${BOOTSTRAP}"
echo

section() {
  echo
  echo "===== $* ====="
}

run() {
  echo "\$ $*"
  "$@" 2>&1 || true
}

section "Python/sendworker-like processes"
run ps -ef

section "Filtered likely consumers"
ps -ef | grep -Ei 'sendworker|module7|module9|recvCommd|test_dataterminal_recv_command|python.*datascratch|python.*sendworker' | grep -v grep || true

section "Processes connected to DataTerminal :8443"
if command -v ss >/dev/null 2>&1; then
  run ss -tnp
elif command -v netstat >/dev/null 2>&1; then
  run netstat -tnp
else
  echo "ss/netstat not found"
fi

section "Filtered :8443 connections"
if command -v ss >/dev/null 2>&1; then
  ss -tnp | grep ':8443' || true
elif command -v netstat >/dev/null 2>&1; then
  netstat -tnp | grep ':8443' || true
fi

section "Kafka tools discovery"
command -v kafka-consumer-groups.sh || true
command -v kafka-consumer-groups || true
find / -name kafka-consumer-groups.sh 2>/dev/null | head -20 || true

KCG=""
if command -v kafka-consumer-groups.sh >/dev/null 2>&1; then
  KCG="$(command -v kafka-consumer-groups.sh)"
elif command -v kafka-consumer-groups >/dev/null 2>&1; then
  KCG="$(command -v kafka-consumer-groups)"
else
  FOUND="$(find / -name kafka-consumer-groups.sh 2>/dev/null | head -1 || true)"
  if [ -n "${FOUND}" ]; then
    KCG="${FOUND}"
  fi
fi

if [ -n "${KCG}" ]; then
  section "Kafka consumer group describe"
  run "${KCG}" --bootstrap-server "${BOOTSTRAP}" --describe --group "${GROUP}"

  section "Kafka consumer groups containing Module"
  "${KCG}" --bootstrap-server "${BOOTSTRAP}" --list 2>&1 | grep -E 'Module|module' || true
else
  echo "Kafka consumer group tool not found; skip Kafka group diagnostics."
fi

section "Topic offsets if kafka-run-class/kafka.tools.GetOffsetShell exists"
if command -v kafka-run-class.sh >/dev/null 2>&1; then
  run kafka-run-class.sh kafka.tools.GetOffsetShell --broker-list "${BOOTSTRAP}" --topic "${TOPIC}" --time -1
else
  FOUND_RUN_CLASS="$(find / -name kafka-run-class.sh 2>/dev/null | head -1 || true)"
  if [ -n "${FOUND_RUN_CLASS}" ]; then
    run "${FOUND_RUN_CLASS}" kafka.tools.GetOffsetShell --broker-list "${BOOTSTRAP}" --topic "${TOPIC}" --time -1
  else
    echo "kafka-run-class.sh not found"
  fi
fi
