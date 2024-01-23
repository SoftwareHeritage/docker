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
      wait-for-it "$(yq -r '.objstorage.url' /content-replayer.yml | cut -d/ -f3)"
      wait-for-it "$(yq -r '.objstorage_dst.url' /content-replayer.yml | cut -d/ -f3)"
      wait-for-it kafka:9092 -s --timeout=0
      echo "Starting the SWH mirror content replayer"
      exec swh --log-level ${LOG_LEVEL:-WARNING} \
           objstorage replay $@
      ;;
    "rpc")
      shift
      swh_start_rpc objstorage
      ;;
esac
