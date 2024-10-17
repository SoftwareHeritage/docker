#!/bin/bash

set -e

source /srv/softwareheritage/utils/pyutils.sh
source /srv/softwareheritage/utils/pgsql.sh
source /srv/softwareheritage/utils/swhutils.sh

setup_pgsql
setup_pip

wait_task_types() {
    echo "Waiting for loader task types to be registered in scheduler db"
    until python3 -c "
from celery import Celery
app = Celery('swh', broker='$BROKER_URL')
for worker_instance in '$WORKER_INSTANCES'.split(','):
    assert any(worker_name.startswith(f'{worker_instance.strip()}@')
            for worker_name in app.control.inspect().active())" 2>/dev/null
    do
        sleep 1
    done
}

case "$1" in
    "shell")
        shift
        if (( $# == 0)); then
            exec bash -i
        else
            "$@"
        fi
        ;;

    "update-metrics")
        wait-for-it swh-scheduler:5008 -s --timeout=0

        echo "Start periodic scheduler metrics update routine (in background)"
        exec sh -c 'trap exit TERM INT; while :; do
        (date && swh scheduler origin update-metrics)
        sleep 60 &
        wait ${!}
        done'
        ;;

    "rpc")
        swh_setup_db scheduler
        echo "Register task types"
        swh scheduler task-type register
        swh_start_rpc scheduler
        ;;

    "worker")
        shift
        wait-for-it swh-scheduler:5008 -s --timeout=0
        wait-for-it amqp:5672 -s --timeout=0

        wait_task_types

        echo "Starting swh scheduler $1"
        exec swh scheduler -C $SWH_CONFIG_FILENAME $@
        ;;

    "journal-client")
      echo "Starting swh-scheduler-journal client"
      wait-for-it kafka:8082 -s --timeout=0
      wait-for-topic http://kafka:8082 swh.journal.objects.origin_visit_status

      exec swh \
           scheduler --config-file $SWH_CONFIG_FILENAME \
           journal-client
      ;;

esac
