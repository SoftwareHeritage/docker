#!/bin/bash

set -e

source /srv/softwareheritage/utils/pyutils.sh
source /srv/softwareheritage/utils/swhutils.sh
source /srv/softwareheritage/utils/pgsql.sh

setup_pip

backend=$(yq -r .storage.cls $SWH_CONFIG_FILENAME)

if [ "$backend" = "pipeline" ]; then
        eval $(cat <<END_OF_PYTHON | python
import yaml
conf = yaml.safe_load(open("$SWH_CONFIG_FILENAME"))
print("backend=" + conf["storage"]["steps"][-1]["cls"])
if any(step["cls"] == "record_references" for step in conf["storage"]["steps"]):
    print("record_references=1")
END_OF_PYTHON
)
fi

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
    remote)
        # No extra setup needed
        ;;
    *)
        echo Unsupported backend "$backend" >&2
        exit 1
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
        fi

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
