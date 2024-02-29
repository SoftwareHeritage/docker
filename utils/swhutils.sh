#!/bin/bash

swh_start_rpc() {
    service=$1
    shift

    echo Starting the swh-${service} API server
    exec gunicorn --bind 0.0.0.0:${RPC_PORT:-5000} \
         --reload \
         --log-level ${LOG_LEVEL:-INFO} \
         --access-logfile /dev/stdout \
         --access-logformat "%(t)s %(r)s %(s)s %(b)s %(M)s" \
         --threads ${GUNICORN_THREADS:-2} \
         --workers ${GUNICORN_WORKERS:-4} \
         --timeout ${GUNICORN_TIMEOUT:-3600} \
         --config 'python:swh.core.api.gunicorn_config' \
         "swh.${service}.api.server:make_app_from_configfile()"

}

swh_start_django() {
  echo "starting the django server..."
  mode=${1:-wsgi}
  if [ "x$mode" == "xdev" ] ; then
      echo "... in dev mode (warning, this does not honor the SCRIPT_NAME env var)"
      # run django development server when overriding swh-web sources
      exec django-admin runserver \
           --nostatic \
           --settings=${DJANGO_SETTINGS_MODULE} \
           0.0.0.0:${RPC_PORT:-5004}
  else
      echo "... using gunicorn on ${RPC_PORT:-5004}"
      # run gunicorn workers as in production otherwise
      exec gunicorn --bind 0.0.0.0:${RPC_PORT:-5004} \
           --reload \
           --log-level ${LOG_LEVEL:-INFO} \
           --access-logfile /dev/stdout \
           --access-logformat "%(t)s %(r)s %(s)s %(b)s %(M)s" \
           --threads ${GUNICORN_THREADS:-2} \
           --workers ${GUNICORN_WORKERS:-2} \
           --timeout ${GUNICORN_TIMEOUT:-3600} \
           --config 'python:swh.web.gunicorn_config' \
           'django.core.wsgi:get_wsgi_application()'
  fi
}

wait-for-topic() {
    KAFKA=$1
    topic=$2
    cluster=$(http --ignore-stdin GET "${KAFKA}/v3/clusters/" | jq -r ".data[0].cluster_id")
    while :
    do
        if http --ignore-stdin --check-status -qq GET "${KAFKA}/v3/clusters/${cluster}/topics/${topic}" &> /dev/null ;
        then
            echo "Topic ${topic} found, exiting"
            break
        fi
        sleep 1
    done
}

wait-for-http() {
    SECONDS=0
    until curl --silent --output /dev/null --fail --location $1
    do
        sleep 1
    done
    echo "$1 is up after ${SECONDS}s"
}

host-port-from-url() {
    # extract the protocol
    proto="$(echo $1 | grep :// | sed -e's,^\(.*://\).*,\1,g')"
    # remove the protocol
    url="$(echo ${1/$proto/})"
    # extract the user (if any)
    user="$(echo $url | grep @ | cut -d@ -f1)"
    # extract the host and port
    hostport="$(echo ${url/$user@/} | cut -d/ -f1)"
    # by request host without port
    host="$(echo $hostport | sed -e 's,:.*,,g')"
    # by request - try to extract the port
    port="$(echo $hostport | sed -e 's,^.*:,:,g' -e 's,.*:\([0-9]*\).*,\1,g' -e 's,[^0-9],,g')"
    echo "${host}:${port:-80}"
}

setup_config_file() {
    if [ ! -f "$SWH_CONFIG_FILENAME" ] && [ -f "${SWH_CONFIG_FILENAME}.in" ]; then
        # templatized...
        export PUBLIC_PORT=`curl -s http://docker-helper/public-port/`
        envsubst <${SWH_CONFIG_FILENAME}.in >${SWH_CONFIG_FILENAME}
    fi
}
