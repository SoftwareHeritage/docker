#!/bin/bash

set -e

source /srv/softwareheritage/utils/pyutils.sh
source /srv/softwareheritage/utils/swhutils.sh
source /srv/softwareheritage/utils/pgsql.sh

setup_pip
# might not be needed, but makes no harm (noop)
setup_pgsql

backend=$(yq -r .storage.cls $SWH_CONFIG_FILENAME)
if yq -e '.storage | .. | select(has("cls") and .cls == "record_references") | .cls' $SWH_CONFIG_FILENAME; then
    record_references=1
fi

case "$backend" in
    "cassandra")
        echo Waiting for Cassandra to start
        IFS=','
        for CASSANDRA_SEED in ${CASSANDRA_SEEDS}; do
            echo "   $CASSANDRA_SEED..."
            wait-for-it ${CASSANDRA_SEED}:9042 -s --timeout=0
        done
        echo Creating keyspace
        cat << EOF | python3
from swh.storage.cassandra import create_keyspace
seeds = [seed.strip() for seed in '${CASSANDRA_SEEDS}'.split(',')]
create_keyspace(seeds, 'swh')
EOF
        ;;
    *)
        # No extra setup needed
        ;;
esac


case "$1" in
    "shell")
      exec bash -i
      ;;
    "swh")
        shift
        echo "Running swh command $@"
        exec swh $@
        ;;
    *)
        # noop if not pg backend is configured
        swh db init-admin --all storage
        swh db init --all storage
        swh db upgrade --all storage

        if [ "$record_references" ]; then
            swh storage create-object-reference-partitions "$(date -I)" "$(date -I -d "next week")"
        fi

        cmd=$1
        shift
        wait-for-it kafka:9092 -s --timeout=0
        wait-for-it kafka:8082 -s --timeout=0
        wait-for-topic http://kafka:8082 swh.journal.objects.snapshot
        case "$cmd" in
            "rpc")
                swh_start_rpc storage
                ;;
            "replayer")
                echo Starting the Kafka storage replayer
                exec swh storage replay $@
                ;;
            "backfiller")
                echo Starting the Kafka storage backfiller
                exec swh storage backfill $@
                ;;
            *)
                echo Unknown command ${cmd}
                ;;
        esac
esac
