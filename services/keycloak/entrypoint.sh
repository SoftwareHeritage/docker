#!/bin/bash

# turn on bash's job control
set -m

echo "Starting Keycloak"
port=$(curl http://docker-helper/public-port/)
/opt/keycloak/bin/kc.sh start-dev --hostname http://localhost:$port/keycloak&
echo "Waiting for Keycloak server to be up"
~/wait-for-it.sh localhost:8080 -s --timeout=0
echo "Configuring Keycloak to be used in docker environment"
echo "and creating some test users in the SoftwareHeritage realm"
/keycloak_swh_setup.py
fg %1
