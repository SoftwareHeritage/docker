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
    "replayer")
      shift
      wait-for-http $(yq -r '.objstorage.url' $SWH_CONFIG_FILENAME)
      wait-for-http $(yq -r '.objstorage_dst.url' $SWH_CONFIG_FILENAME)
      wait-for-it kafka:8082 --timeout=0
      wait-for-topic http://kafka:8082 swh.journal.objects.content
      echo "Starting the SWH mirror content replayer"
      exec swh objstorage replay $@
      ;;
    "rpc")
      shift
      swh_start_rpc objstorage $@
      ;;
    "winery-rpc")
      shift
      echo "Setup Winery DB $NAME"
      wait_pgsql
      swh db init-admin -d service=$POSTGRES_DB objstorage:winery
      swh db init -d service=$POSTGRES_DB objstorage:winery
      swh db upgrade --non-interactive -d service=$POSTGRES_DB objstorage:winery
      #swh_setup_db objstorage
      if [ "$GUNICORN_THREADS" != "1" ]; then
	  echo "Enforce GUNICORN_THREADS to 1"
	  GUNICORN_THREADS="1"
      fi
      swh_start_rpc objstorage $@
      ;;
    "winery-packer")
      shift
      wait-for-http http://swh-objstorage:5003/
      exec swh objstorage winery packer $@
      ;;
    "winery-cleaner")
      shift
      echo "Starting cleaner"
      wait-for-http http://swh-objstorage:5003/
      exec swh objstorage winery rw-shard-cleaner --min-mapped-hosts=0 $@
      ;;
esac
