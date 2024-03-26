#!/bin/bash

set -e

source /srv/softwareheritage/utils/pyutils.sh
source /srv/softwareheritage/utils/swhutils.sh
source /srv/softwareheritage/utils/pgsql.sh

setup_pip

backend=$(yq -r .storage.cls $SWH_CONFIG_FILENAME)

case "$backend" in
    "postgresql")
        setup_pgsql
        ;;
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
        if [ "$backend" = "postgresql" ]; then
            swh_setup_db storage

            if [[ -n $REPLICA_SRC ]]; then
                swh_setup_dbreplica
            fi
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
                exec swh --log-level ${LOG_LEVEL:-WARNING} storage replay $@
                ;;
            "backfiller")
                echo Starting the Kafka storage backfiller
                exec swh --log-level ${LOG_LEVEL:-WARNING} storage backfill $@
                ;;
            *)
                echo Unknown command ${cmd}
                ;;
        esac
esac
