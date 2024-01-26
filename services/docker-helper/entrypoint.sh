#!/bin/bash

set -e

pip install requests-unixsocket

case "$1" in
    "shell")
      exec bash -i
      ;;
    "rpc")
        echo Starting the docker helper API server
        exec gunicorn --bind 0.0.0.0:${RPC_PORT:-80} \
         --reload \
         --log-level ${LOG_LEVEL:-INFO} \
         --access-logfile /dev/stdout \
         --access-logformat "%(t)s %(r)s %(s)s %(b)s %(M)s" \
         --threads ${GUNICORN_THREADS:-2} \
         --workers ${GUNICORN_WORKERS:-2} \
         --timeout ${GUNICORN_TIMEOUT:-3600} \
         "app:app"
      ;;
esac
