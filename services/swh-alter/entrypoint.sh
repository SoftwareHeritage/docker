#!/bin/bash

set -e

source /srv/softwareheritage/utils/pgsql.sh
source /srv/softwareheritage/utils/pyutils.sh
source /srv/softwareheritage/utils/swhutils.sh

setup_pip
setup_pgsql

case "$1" in
    "shell")
      exec bash -i
      ;;
    "run-mirror-notification-watcher")
      shift
      wait-for-it kafka:8082 --timeout=0
      wait-for-topic http://kafka:8082 swh.journal.mirror-notifications.removal_notification
      exec swh alter run-mirror-notification-watcher "$@"
      ;;
    *)
      exec python /src/alter_companion.py "$@"
      ;;
esac
