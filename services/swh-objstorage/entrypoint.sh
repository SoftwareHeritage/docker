#!/bin/bash

set -e

source /srv/softwareheritage/utils/pyutils.sh
source /srv/softwareheritage/utils/swhutils.sh

setup_pip

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
      swh_start_rpc objstorage
      ;;
esac
