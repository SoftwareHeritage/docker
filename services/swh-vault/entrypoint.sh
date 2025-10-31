#!/bin/bash

set -e

source /srv/softwareheritage/utils/pyutils.sh
source /srv/softwareheritage/utils/pgsql.sh
source /srv/softwareheritage/utils/swhutils.sh

setup_pip
setup_pgsql
setup_config_file

case "$1" in
    "shell")
        exec bash -i
        ;;

    "worker")
        echo Waiting for the scheduler
        wait-for-it $SWH_SCHEDULER_HOST:5008 -s --timeout=0

        if ! ping -c 1 swh-graph; then
            # swh-graph service not available, remove graph config to
            # prevent vault worker from crashing when creating cookers
            yq 'del(.vault.graph)' $SWH_CONFIG_FILENAME > /srv/softwareheritage/config-no-graph.yml
            export SWH_CONFIG_FILENAME=/srv/softwareheritage/config-no-graph.yml
        fi

        echo Starting the swh-vault Celery worker
        exec python -m celery \
                    --app=swh.scheduler.celery_backend.config.app \
                    worker \
                    --pool=prefork --events \
                    --concurrency=${CONCURRENCY} \
                    --max-tasks-per-child=${MAX_TASKS_PER_CHILD} \
                    -Ofair --loglevel=${LOG_LEVEL:-INFO} \
                    --hostname "vault@%h"
        ;;

    "rpc")
        shift
        # ensure the pathslicing root dir for the cache exists
        mkdir -p /srv/softwareheritage/vault
        swh_setup_db vault
        swh_start_rpc vault
        ;;
esac
