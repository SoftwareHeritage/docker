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
        swh_setup_db indexer_storage
        swh_start_rpc indexer.storage
        ;;

    "journal-client")
        echo "Starting swh-indexer-journal client"
        wait-for-it swh-idx-storage:5007 -s --timeout=0
        wait-for-it kafka:8082 -s --timeout=0
		wait-for-topic http://kafka:8082 swh.journal.objects.origin_visit_status
        exec swh indexer $@
        ;;

esac
