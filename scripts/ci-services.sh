#!/usr/bin/env bash
set -euo pipefail

case "${1:-start}" in
  start)
    podman run -d --name quetz-ci-postgres \
      -e POSTGRES_PASSWORD=mysecretpassword -e POSTGRES_DB=postgres \
      -p 127.0.0.1:5432:5432 \
      --health-cmd pg_isready --health-interval 2s --health-retries 30 \
      docker.io/library/postgres:16
    podman run -d --name quetz-ci-redis -p 127.0.0.1:6379:6379 \
      --health-cmd 'redis-cli ping' --health-interval 2s --health-retries 30 \
      docker.io/library/redis:7
    for service in quetz-ci-postgres quetz-ci-redis; do
      ready=false
      for attempt in {1..60}; do
        if [ "$(podman inspect --format '{{.State.Health.Status}}' "$service")" = healthy ]; then
          ready=true
          break
        fi
        sleep 1
      done
      if [ "$ready" != true ]; then
        podman logs "$service"
        exit 1
      fi
    done
    ;;
  stop)
    podman rm -f --ignore quetz-ci-postgres quetz-ci-redis
    ;;
  *)
    echo "Usage: $0 [start|stop]" >&2
    exit 2
    ;;
esac
