#!/bin/bash

set -e

source /srv/softwareheritage/utils/pgsql.sh
setup_pgsql

source /srv/softwareheritage/utils/pyutils.sh
setup_pip

source /srv/softwareheritage/utils/swhutils.sh
setup_config_file

# refresh save code now statuses every 15 seconds
function refresh_savecodenow_statuses_cron() {
    echo "Start periodic save code now refresh statuses routine (in background)"
    exec sh -c 'trap exit TERM INT; while :; do
    (echo "refresh_savecodenow_statuses: $(date)" &&
     django-admin refresh_savecodenow_statuses --settings=${DJANGO_SETTINGS_MODULE} 2>&1)
    sleep 15 &
    wait ${!}
    done'
}

# generate archive coverage data every 5 minutes
function generate_coverage_data_cron() {
    echo "Start periodic archive coverage data computation routine (in background)"
    exec sh -c 'trap exit TERM INT; while :; do
    (echo "generate_coverage_data: $(date)" &&
     django-admin generate_coverage_data --settings=${DJANGO_SETTINGS_MODULE} 2>&1)
    sleep 300 &
    wait ${!}
    done'
}

case "$1" in
    "noop")
        echo "Doing nothing..."
        exec sleep 60
        ;;
    "shell")
        exec bash -i
        ;;
    "cron")
        echo "Waiting for swh-web..."
        wait-for-it swh-web:5004 -s --timeout=0
        if [[ ! -v DISABLE_SCN_STATUS_REFRESH_CRON ]]; then
            refresh_savecodenow_statuses_cron&
        fi
        generate_coverage_data_cron&
        # do not exit as cron jobs are executed in background
        tail -f /dev/null
        ;;
     *)
        wait_pgsql

        echo "Migrating db using ${DJANGO_SETTINGS_MODULE}"
        django-admin migrate --settings=${DJANGO_SETTINGS_MODULE}

        echo "Creating Django test users"
        SWH_WEB_SRC_DIR=$(python3 -c "import os; from swh import web; print(os.path.dirname(web.__file__))")
        for create_user_script in $SWH_WEB_SRC_DIR/tests/create_test_*
        do
            cat $create_user_script | python3 -m swh.web.manage shell
        done

        swh_start_django
esac
