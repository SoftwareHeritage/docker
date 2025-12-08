#!/bin/bash

set -ex

source /srv/softwareheritage/utils/pyutils.sh
setup_pip

source /srv/softwareheritage/utils/pgsql.sh
setup_pgsql

source /srv/softwareheritage/utils/swhutils.sh

if [ "$1" = 'shell' ] ; then
    shift
    if (( $# == 0)); then
        exec bash -i
    else
        "$@"
    fi
elif [ "$1" = 'worker' ] ; then

    # FIXME
    pip install git+https://gitlab.softwareheritage.org/swh/devel/swh-coarnotify.git@tasks\#egg=swh.coarnotify

    echo Waiting for the scheduler
    wait-for-it $SWH_SCHEDULER_HOST:5008 -s --timeout=0

    echo Waiting for RabbitMQ to start
    wait-for-it amqp:5672 -s --timeout=0

    echo Starting the swh-coarnotify Celery worker
    exec python -m celery \
                --app=swh.scheduler.celery_backend.config.app \
                worker \
                --pool=prefork --events \
                --concurrency=${CONCURRENCY} \
                --max-tasks-per-child=${MAX_TASKS_PER_CHILD} \
                -Ofair --loglevel=${LOG_LEVEL:-INFO} \
                --hostname "coarnotify@%h"
else
    wait_pgsql

    echo "Migrating db"
    django-admin migrate --settings=${DJANGO_SETTINGS_MODULE}
    echo "Loading dev fixtures"
    django-admin devusers --settings=${DJANGO_SETTINGS_MODULE}
    swh_start_django
fi
