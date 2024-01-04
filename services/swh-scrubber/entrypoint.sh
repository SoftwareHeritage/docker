#!/bin/bash

set -e

source /srv/softwareheritage/utils/pyutils.sh
setup_pip

source /srv/softwareheritage/utils/pgsql.sh
setup_pgsql

case "$1" in
    "shell")
      exec bash -i
      ;;

    "init")
        shift
        swh_setup_db scrubber
        touch scrubber_db_initialized
        echo "Scrubbing db initialized, puting the service to sleep..."
        exec sleep infinity
        ;;

    "config")
        shift
        # expected arguments: entity type, number of partitions (as nbits)
        OBJTYPE=$1
        shift
        NBITS=$1
        shift
        CFGNAME="${OBJTYPE}_${NBITS}"
        # now create the scrubber config, if needed
        swh scrubber check init storage \
            --object-type ${OBJTYPE} \
            --nb-partitions $(( 2 ** ${NBITS} )) \
            --name ${CFGNAME} && \
            echo "Created scrubber configuration ${CFGNAME}" || \
                echo "Configuration ${CFGNAME} already exists (ignored)."
        ;;

    "run")
        shift
        CFGNAME=$1
        shift

        echo "Starting a SWH storage scrubber ${CFGNAME}"
        swh --log-level ${LOG_LEVEL:-WARNING} \
            scrubber check storage ${CFGNAME} $@
        ;;

    *)
        exec $@
        ;;
esac
