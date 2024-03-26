#!/bin/bash
# /cassandra-override.yaml is provided by compose via a bind-mount, and only
# contains entries that cannot be set using environment variables. Add them at
# the end of the existing config file provided by the docker image so they take
# precedence (last talker wins).
cat /cassandra-override.yaml >> /etc/cassandra/cassandra.yaml
exec docker-entrypoint.sh
