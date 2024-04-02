#!/bin/bash

set -e

source /srv/softwareheritage/utils/pyutils.sh
source /srv/softwareheritage/utils/swhutils.sh
source /srv/softwareheritage/utils/pgsql.sh

setup_pip

setup_pgsql

case "$1" in
    "shell")
      exec bash -i
      ;;
    "swh")
        shift
        echo "Running swh command $@"
        exec swh $@
        ;;
    "rpc")
        swh db init-admin --dbname postgresql:///?service=swh-masking storage.proxies.masking
        swh db init --dbname postgresql:///?service=swh-masking storage.proxies.masking
        swh db upgrade --dbname postgresql:///?service=swh-masking --non-interactive storage.proxies.masking

        swh_start_rpc storage
	;;
    *)
	echo Unknown command ${1}
	;;
esac
