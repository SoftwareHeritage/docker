#!/bin/bash

set -e

# when using an editable install of swh-web (when testing changes from
# a merge request for instance), ensure to generate static assets
if [ -d /src/swh-web ] ; then
    echo "Install and compile swh-web static assets"
    (cd /src/swh-web &&
     yarn install --frozen-lockfile &&
     yarn build-dev)
fi

source /srv/softwareheritage/utils/pgsql.sh
setup_pgsql

source /srv/softwareheritage/utils/pyutils.sh
setup_pip

source /srv/softwareheritage/utils/swhutils.sh
setup_config_file

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

        echo "Start periodic save code now refresh statuses routine (in background)"
        exec sh -c 'trap exit TERM INT; while :; do
        (date && django-admin refresh_savecodenow_statuses \
                  --settings=${DJANGO_SETTINGS_MODULE} 2>&1)
        sleep 15 &
        wait ${!}
        done'
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
