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
else
    wait_pgsql
    # XXX
    pip install git+https://gitlab.softwareheritage.org/swh/devel/swh-coarnotify.git@prototype\#egg=swh.coarnotify

    echo "Migrating db"
    django-admin migrate --settings=${DJANGO_SETTINGS_MODULE}
    echo "Loading dev fixtures"
    django-admin devusers --settings=${DJANGO_SETTINGS_MODULE}
    swh_start_django
fi
