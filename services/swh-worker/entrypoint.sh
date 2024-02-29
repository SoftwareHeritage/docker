#!/bin/bash

set -e

source /srv/softwareheritage/utils/swhutils.sh
source /srv/softwareheritage/utils/pyutils.sh
setup_pip

case "$1" in
    "shell")
        shift
        echo "Running command $@"
        exec bash -i "$@"
        ;;

    "swh")
        shift
        wait-for-it swh-storage:5002 -s --timeout=0
        echo "Running swh command $@"
        exec swh $@
        ;;

    "worker")
        echo Waiting for the scheduler
        wait-for-http ${SWH_SCHEDULER_INSTANCE}

        echo Waiting for RabbitMQ to start
        wait-for-it amqp:5672 -s --timeout=0

        # make sure workers (esp. loaders) do not try to ingest content while
        # the storage is actually not ready yet.
        echo Waiting for the storage to start
        wait-for-it swh-storage:5002 -s --timeout=0

        echo Starting the swh Celery worker for ${SWH_WORKER_INSTANCE}
        exec python -m celery \
                    --app=swh.scheduler.celery_backend.config.app \
                    worker \
                    --pool=prefork --events \
                    --concurrency=${CONCURRENCY} \
                    --max-tasks-per-child=${MAX_TASKS_PER_CHILD} \
                    -Ofair --loglevel=${LOG_LEVEL:-INFO} \
                    --hostname "${SWH_WORKER_INSTANCE}@%h"
        ;;
esac
