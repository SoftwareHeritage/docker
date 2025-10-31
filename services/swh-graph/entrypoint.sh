#!/bin/bash

set -e

source /srv/softwareheritage/utils/pyutils.sh
setup_pip

source /srv/softwareheritage/utils/pgsql.sh
setup_pgsql

DATADIR=/srv/softwareheritage/graph

update_graph() {
  mkdir -p $DATADIR/
  # cleanup results from previous runs
  rm -rf $DATADIR/*

  # export graph to ORC
  swh export graph export --export-name test -f orc \
    --sensitive-export-path /srv/softwareheritage/graph/sensitive \
    /srv/softwareheritage/graph

  # compress graph from ORC
  swh graph compress -i /srv/softwareheritage/graph/orc/ \
    --sensitive-input-dataset /srv/softwareheritage/graph/sensitive/orc/ \
    -o /srv/softwareheritage/graph/compressed \
    --sensitive-output-directory /srv/softwareheritage/graph/sensitive/compressed \
    --check-flavor none

  # copy export.json to the path expected by the GRPC server
  cp /srv/softwareheritage/graph/meta/export.json /srv/softwareheritage/graph/compressed/meta/

  # notify that graph RPC servers must be restarted
  touch graph.stamp
}

check_archive_update() {
  # poll regularly number of snapshots in the archive and update graph
  # when new ones were added
  last_nb_snapshots=$(curl -s http://nginx/api/1/stat/counters/ | jq '.snapshot')
  while true; do
    nb_snapshots=$(curl -s http://nginx/api/1/stat/counters/ | jq '.snapshot')
    if [ $last_nb_snapshots != $nb_snapshots ]; then
      echo "Archive content was updated, regenerating compressed graph"
      last_nb_snapshots=$nb_snapshots
      update_graph
    fi
    sleep 10
  done
}

generate_masked_nodes_file() {
  echo "Generating list of masked SWHIDs"
  psql service=swh-masking -qt -c \
    "select 'swh:1:' || object_type::text || ':' || encode(object_id::bytea, 'hex') from masked_object;" | \
    sed 's/content/cnt/g' | sed 's/directory/dir/g' | sed 's/origin/ori/g' | sed 's/release/rel/g' | \
    sed 's/revision/rev/g' | sed 's/snapshot/snp/g' | sed '/raw_extrinsic_metadata/d' | \
    sed '/^$/d' | sed 's/^ *//;s/ *$//' > /srv/softwareheritage/graph/masked_nodes
}

check_masking_update() {
  # poll regularly number of masked objects in the archive and restart graph RPC
  # servers when changes are detected so the list of masked SWHIDs gets updated
  last_masked_objects_hash=$(psql service=swh-masking -qt -c \
    "select bit_xor(('x'||substr(md5(object_id),1,16))::bit(64)::bigint) from masked_object;")
  while true; do
    masked_objects_hash=$(psql service=swh-masking -qt -c \
      "select bit_xor(('x'||substr(md5(object_id),1,16))::bit(64)::bigint) from masked_object;")
    if [ "$last_masked_objects_hash" != "$masked_objects_hash" ]; then
      echo "Objects masking was updated, list of masked SWHIDs must be updated"
      last_masked_objects_hash=$masked_objects_hash
      # notify that graph RPC servers must be restarted
      touch graph.stamp
    fi
    sleep 10
  done
}

# wait for required services to be up
wait-for-it swh-storage:5002 -s --timeout=0
wait-for-it swh-counters:5011 -s --timeout=0
wait-for-it swh-web:5004 -s --timeout=0

while true; do
  nb_snapshots=$(curl -s http://nginx/api/1/stat/counters/ | jq '.snapshot')
  if [ $nb_snapshots == 0 ]; then
    echo "Waiting for the archive to be populated before exporting its graph"
  else
    break
  fi
  sleep 5
done

case "$1" in
    "shell")
      exec bash -i
      ;;
    *)
      if [[ ! -d $DATADIR/compressed ]] ; then
        # Generate the graph if it wasn't already
        update_graph
      fi
      generate_masked_nodes_file
      echo "Starting the swh-graph RPC servers"
      swh --log-level DEBUG graph rpc-serve --graph /srv/softwareheritage/graph/compressed/graph &
      # execute that function in background to poll changes in the archive
      check_archive_update &
      # execute that function in background to poll changes in masked objects
      check_masking_update &
      touch graph.stamp
      # restart RPC and GRPC servers when graph was updated
      inotifywait -q -m -e attrib graph.stamp |
      while read -r filename event; do
        echo "Restarting the swh-graph RPC servers"
        kill -9 $(pgrep -f swh)
        generate_masked_nodes_file
        swh --log-level DEBUG graph rpc-serve --graph /srv/softwareheritage/graph/compressed/graph &
      done
      ;;
esac
