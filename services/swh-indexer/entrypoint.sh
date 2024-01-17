#!/bin/bash

set -e

source /srv/softwareheritage/utils/pyutils.sh
source /srv/softwareheritage/utils/pgsql.sh
source /srv/softwareheritage/utils/swhutils.sh

setup_pip
setup_pgsql

case "$1" in
    "shell")
        exec bash -i
        ;;

    "rpc")
        swh_setup_db indexer
        swh_start_rpc indexer.storage
        ;;

    "worker")
        echo Waiting for RabbitMQ to start
        wait-for-it amqp:5672 -s --timeout=0
        echo Waiting for Indexer Storage
        wait-for-it swh-idx-storage:5007 -s --timeout=0

        echo Starting swh-indexer Celery-based worker
        exec python -m celery \
             --app=swh.scheduler.celery_backend.config.app \
             worker \
             --pool=prefork --events \
             --concurrency=${CONCURRENCY} \
             --max-tasks-per-child=${MAX_TASKS_PER_CHILD} \
             -Ofair --loglevel=${LOG_LEVEL:-INFO} \
             --hostname "${SWH_WORKER_INSTANCE}@%h"
        ;;

    "journal-client")
        echo "Starting swh-indexer-journal client"
        wait-for-it swh-idx-storage:5007 -s --timeout=0
        wait-for-it kafka:8082 -s --timeout=0
		wait-for-topic http://kafka:8082 swh.journal.objects.origin_visit_status

        # note that specifying the 'indexer' argument of the 'swh indexer
        # journal-client' command makes it behave differently, indexing objects
        # directly rather than spawning scheduler tasks to do the actual
        # indexing job.
        # This later behaviour should be now considered as deprecated.
        exec swh \
             indexer --config-file $SWH_CONFIG_FILENAME \
             journal-client 'origin_intrinsic_metadata'
        ;;

esac
