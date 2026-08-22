#!/bin/sh
# wait-for.sh HOST PORT [TIMEOUT_SECONDS] -- command...
# Minimal dependency gate for containers whose image has no healthcheck client.
set -eu

host=$1; port=$2; timeout=${3:-60}
shift 3
[ "${1:-}" = "--" ] && shift

elapsed=0
until nc -z "$host" "$port" 2>/dev/null; do
  elapsed=$((elapsed + 1))
  if [ "$elapsed" -ge "$timeout" ]; then
    echo "timed out waiting for $host:$port after ${timeout}s" >&2
    exit 1
  fi
  sleep 1
done

exec "$@"
