Docker environment
==================

This ``docker`` repository contains Dockerfiles to run a small Software Heritage
instance on a development machine. The end goal is to smooth the
contributors/developers workflow. Focus on coding, not configuring!

.. warning::
   Running a Software Heritage instance on your machine can
   consume quite a bit of resources: if you play a bit too hard (e.g., if
   you try to list all GitHub repositories with the corresponding lister),
   you may fill your hard drive, and consume a lot of CPU, memory and
   network bandwidth.

It is generally used as a subdirectory of the `swh-environment` (but not necessarily).

Dependencies
------------

We recommend using the latest version of docker, so please read
https://docs.docker.com/install/linux/docker-ce/debian/ for more details
on how to install Docker on your machine.

This environment uses Docker `Compose`_, so ensure you have a working
Docker environment and that the docker compose plugin (>= 2.24.4) `is installed
<https://docs.docker.com/compose/install/>`_.

.. _Compose: https://docs.docker.com/compose/


Service "packs"
---------------

The Software Heritage stack consists in many services running along each other
to implement the full feature set of the SWH platform.

However not all these services are required all the time for someone playing
with this toy, and launching the stack full blast can be pretty resource heavy
on the user's machine.

So we divided the services in several "sets" that can be enabled or not. Each
of these feature sets can be started by using the corresponding compose file,
in addition to the main one. Provided compose files are:

- `compose.yml`: the main compose file, firing basic (core) SWH services (see
  below). You can browse the archive using the URL http://localhost:<publicport>
  (`<publicport>` being the port chosen by docker for the service
  ``nginx``).

- `compose.cassandra.yml`: replace the backend of the main `swh-storage`
  service by Cassandra (instead of Postgresql).

- `compose.deposit.yml`: activate the swh-deposit_ feature set of the
  SWH stack.

- `compose.graph.yml`: add the swh-graph_ feature. This may require some manual
  commands to (re)generate the graph dataset used by swh-graph.

- `compose.keycloak.yml`: activate the keycloak-based auhentication
  backend for the web frontend (without it, you only have the django-based
  authentication mechanism included in swh-web_).

- `compose.mirror.yml`: deploy a complete SWH mirror stack in a
  dedicated environment: you can browse the mirror using the URL
  http://localhost:<publicport> (`<publicport>` being the port chosen by docker
  for the service ``nginx-mirror``).

- `compose.scrubber.yml`: deploy swh-scrubber_ services (scrubbing the
  Postgresql storage only for now, so incompatible with the
  `compose.cassandra.yml` override).

- `compose.search.yml`: replace the in-memory search engine backend for
  the SWH archive by an ElasticSearch based one (see swh-search_).

- `compose.vault.yml`: activate the swh-vault_ feature of the SWH stack.

.. _`pglogical`: https://github.com/2ndQuadrant/pglogical
.. _swh-deposit: https://docs.softwareheritage.org/devel/swh-deposit
.. _swh-graph: https://docs.softwareheritage.org/devel/swh-graph
.. _swh-graphql: https://docs.softwareheritage.org/devel/swh-graphql
.. _swh-web: https://docs.softwareheritage.org/devel/swh-web
.. _swh-scrubber: https://docs.softwareheritage.org/devel/swh-scrubber
.. _swh-vault: https://docs.softwareheritage.org/devel/swh-vault
.. _swh-search: https://docs.softwareheritage.org/devel/swh-search

Activating one (or several) of these feature "packs" is a matter of either use
the appropriate `--file` options of the `docker compose` command, or define the
`COMPOSE_FILE` environment variable.

For example:

.. code-block:: console

   ~/swh-environment/docker$ export COMPOSE_FILE=compose.yml:compose.search.yml:compose.mirror.yml
   ~/swh-environment/docker$ docker compose up -d
   [...]


Details of the main service set
-------------------------------

The main `compose.yml` file defines the following services (among others):

- swh-storage-db: a ``softwareheritage`` instance db that stores the Merkle
  DAG,

- swh-objstorage: Content-addressable object storage; it uses a docker volume
  to store the objects using the pathslicer_ backend,

- swh-storage: Abstraction layer over the archive, allowing to access all
  stored source code artifacts as well as their metadata, mostly used in write
  scenarios or when full access is required,

- swh-storage-public: Same as `swh-storage` but intended for public read
  scenarios (e.g. swh-web, swh-vault) with the masking proxy enabled,

- swh-web: the Software Heritage web user interface (with a default "admin"
  account with password "admin"),

- swh-scheduler: the API service as well as a series of utilities (runner,
  listener, metrics...),

- swh-lister: celery workers dedicated to running lister tasks,

- swh-loaders: celery workers dedicated to importing/updating source code
  content (VCS repos, source packages, etc.),

- swh-journal: Persistent logger of changes to the archive, with
  publish-subscribe support. This consists in a Kafka journal and a series of
  producers (typically the storage or indexers) and consumers (generally called
  `xxx-journal-client`).

That means you can start doing the ingestion using those services using
the same setup described in the getting-started starting directly at
https://docs.softwareheritage.org/devel/getting-started.html#step-4-ingest-repositories

Note that in addition to these core SWH services, the main compose file also
defines all the required backend services:

- nginx, used as main edge proxy for all "public" services running in
  the compose environment,
- rabbitmq (amqp),
- kafka (with a kafka-ui frontend),
- prometheus (with several helper tools),
- grafana,
- mailpit,
- redis,
- memcache.


.. _pathslicer: https://docs.softwareheritage.org/devel/apidoc/swh.objstorage.backends.pathslicing.html


Exposed Ports
^^^^^^^^^^^^^

The only services exposing a port are the main nginx dispatchers (on internal
port 80). The public port is chosen by docker compose so it does not collide
with any use port on the host.

That means that if you want to access the archive running in the compose
session, you need to ask docker compose about the port to use for that::

   ~/swh-environment/docker$ docker compose port nginx 80
   0.0.0.0:34081

If you really want to make it use a fixed port instead, either modify the main
`compose.yml` file accordingly, or use an override file like::

   ~/swh-environment/docker$ cat compose.override.yml
   services:
     nginx:
       ports:
         - "5080:80"

You generally just need to run commands from within a running container, so you
may use all the default host and ports of services running in the compose
session. For example to show the Celery status::

   ~/swh-environment/docker$ docker compose exec swh-scheduler celery status
   loader@61704103668c: OK
   [...]


The services exposing internal ports on the host are:

- ``nginx`` from the main ``compose.yml`` file,
- ``nginx-mirror`` from the ``compose.mirror.yml`` file.

Useful services are then exposed by nginx via URL routing:

- ``/``: main SWH archive web app,
- ``/deposit``: swh-deposit_ public and private API
- ``/grafana``: the Grafana dashboard for Prometheus
- ``/kafka-ui``: the kafka-UI dashboard for kafka
- ``/mail``: the mailpit dashboard
- ``/prometheus``: the Prometheus monitoring service
- ``/graphql``: swh-graphql_ public graphQL API (if available)
- ``/keycloak``: the Keycloak service (if available)
- ``/svix``: the weebook engine svix API (if available)
- ``/azure``: the Azurite_-based Azure API (if available)
- ``/es``: access the ElasticSearch service (if available)
- ``/coarnotify``: access the COAR Notify service (if available)

Software Heritage internal (RPC) APIs are exposed as well for testing purpose
under the ``/rpc`` "namespace":

- ``/rpc/scheduler``
- ``/rpc/storage``
- ``/rpc/objstorage``
- ``/rpc/indexer-storage``
- ``/rpc/search``
- ``/rpc/vault``
- ``/rpc/counters``

.. _Azurite: https://github.com/Azure/Azurite

.. _docker-manage-tasks:

Managing tasks
--------------

One of the main components of the Software Heritage platform is the task
system. These are used to manage everything related to background
process, like discovering new git repositories to import, ingesting
them, checking a known repository is up to date, etc.

The task system is based on Celery but uses a custom database-based
scheduler.

So when we refer to the term ‘task’, it may designate either a Celery
task or a SWH one (ie. the entity in the database). When we refer to
simply a “task” in the documentation, it designates the SWH task.

When a SWH task is ready to be executed, a Celery task is created to
handle the actual SWH task’s job. Note that not all Celery tasks are
directly linked to a SWH task (some SWH tasks are implemented using a
Celery task that spawns Celery subtasks).

A (SWH) task can be ``recurring`` or ``oneshot``. ``oneshot`` tasks are
only executed once, whereas ``recurring`` are regularly executed. The
scheduling configuration of these recurring tasks can be set via the
fields ``current_interval`` and ``priority`` (can be ‘high’, ‘normal’ or
‘low’) of the task database entity.

.. _docker-schedule-lister-task:

Inserting a new lister task
^^^^^^^^^^^^^^^^^^^^^^^^^^^

To list the content of a source code provider like github or a Debian
distribution, you may add a new task for this.

This task will (generally) scrape a web page or use a public API to
identify the list of published software artefacts (git repos, debian
source packages, etc.)

Then, for each repository, a new task will be created to ingest this
repository and keep it up to date.

For example, to add a (one shot) task that will list git repos on the
0xacab.org gitlab instance, one can do (from this git repository)::

   ~/swh-environment/docker$ docker compose exec swh-scheduler \
       swh scheduler task add list-gitlab-full \
         -p oneshot url=https://0xacab.org/api/v4

   Created 1 tasks

   Task 12
     Next run: just now (2018-12-19 14:58:49+00:00)
     Interval: 90 days, 0:00:00
     Type: list-gitlab-full
     Policy: oneshot
     Args:
     Keyword args:
       url=https://0xacab.org/api/v4

This will insert a new task in the scheduler. To list existing tasks for
a given task type::

   ~/swh-environment/docker$ docker compose exec swh-scheduler \
     swh scheduler task list-pending list-gitlab-full

   Found 1 list-gitlab-full tasks

   Task 12
     Next run: 2 minutes ago (2018-12-19 14:58:49+00:00)
     Interval: 90 days, 0:00:00
     Type: list-gitlab-full
     Policy: oneshot
     Args:
     Keyword args:
       url=https://0xacab.org/api/v4

To list all existing task types::

   ~/swh-environment/docker$ docker compose exec swh-scheduler \
     swh scheduler task-type list

   Known task types:
   load-svn-from-archive:
     Loading svn repositories from svn dump
   load-svn:
     Create dump of a remote svn repository, mount it and load it
   load-deposit:
     Loading deposit archive into swh through swh-loader-tar
   check-deposit:
     Pre-checking deposit step before loading into swh archive
   cook-vault-bundle:
     Cook a Vault bundle
   load-hg:
     Loading mercurial repository swh-loader-mercurial
   load-hg-from-archive:
     Loading archive mercurial repository swh-loader-mercurial
   load-git:
     Update an origin of type git
   list-github-incremental:
     Incrementally list GitHub
   list-github-full:
     Full update of GitHub repos list
   list-debian-distribution:
     List a Debian distribution
   list-gitlab-incremental:
     Incrementally list a Gitlab instance
   list-gitlab-full:
     Full update of a Gitlab instance's repos list
   list-pypi:
     Full pypi lister
   load-pypi:
     Load Pypi origin
   index-mimetype:
     Mimetype indexer task
   index-mimetype-for-range:
     Mimetype Range indexer task
   index-fossology-license:
     Fossology license indexer task
   index-fossology-license-for-range:
     Fossology license range indexer task
   index-origin-head:
     Origin Head indexer task
   index-revision-metadata:
     Revision Metadata indexer task
   index-origin-metadata:
     Origin Metadata indexer task

Monitoring activity
^^^^^^^^^^^^^^^^^^^

You can monitor the workers activity by connecting to the RabbitMQ
console on ``http://localhost:<publicport>/rabbitmq`` or the grafana dashboard
on ``http://localhost:<publicport>/grafana``.

If you cannot see any task being executed, check the logs of the
``swh-scheduler-runner`` service (here is a failure example due to the
debian lister task not being properly registered on the
swh-scheduler-runner service)::

   ~/swh-environment/docker$ docker compose logs --tail=10 swh-scheduler-runner
   Attaching to docker_swh-scheduler-runner_1
   swh-scheduler-runner_1    |     "__main__", mod_spec)
   swh-scheduler-runner_1    |   File "/usr/local/lib/python3.7/runpy.py", line 85, in _run_code
   swh-scheduler-runner_1    |     exec(code, run_globals)
   swh-scheduler-runner_1    |   File "/usr/local/lib/python3.7/site-packages/swh/scheduler/celery_backend/runner.py", line 107, in <module>
   swh-scheduler-runner_1    |     run_ready_tasks(main_backend, main_app)
   swh-scheduler-runner_1    |   File "/usr/local/lib/python3.7/site-packages/swh/scheduler/celery_backend/runner.py", line 81, in run_ready_tasks
   swh-scheduler-runner_1    |     task_types[task['type']]['backend_name']
   swh-scheduler-runner_1    |   File "/usr/local/lib/python3.7/site-packages/celery/app/registry.py", line 21, in __missing__
   swh-scheduler-runner_1    |     raise self.NotRegistered(key)
   swh-scheduler-runner_1    | celery.exceptions.NotRegistered: 'swh.lister.debian.tasks.DebianListerTask'

Using docker setup development and integration testing
------------------------------------------------------

If you hack the code of one or more archive components with a virtual
env based setup as described in the
`developer setup guide <https://docs.softwareheritage.org/devel/developer-setup.html>`__, you may want to test your modifications in a working
Software Heritage instance. The simplest way to achieve this is to use
this docker-based environment.

If you haven’t followed the `developer setup guide
<https://docs.softwareheritage.org/devel/developer-setup.html>`__, you must
clone the the `swh-environment`_ repo::

   ~$ git clone https://gitlab.softwareheritage.org/swh/devel/swh-environment.git
   [...]
   ~$ cd swh-environment
   ~/swh-environment$

From there, we will checkout or update all the ``swh`` packages::

   ~/swh-environment$ ./bin/update

This later command will clone the ``docker`` repository in the
``swh-environment/`` directory, as well as all the active swh package source
repositories.

.. _`swh-environment`: https://gitlab.softwareheritage.org/swh/devel/swh-environment


Install a swh package from sources in a container
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

It is possible to run a docker container with some swh packages
installed from sources instead of using the latest published packages
from pypi. To do this you must write a
`Docker Compose override file <https://docs.docker.com/compose/extends>`_
(``compose.override.yml``). An example is given in the
``compose.override.yml.example`` file:

.. code:: yaml

   version: '2'

   services:
     swh-objstorage:
       volumes:
         - "$HOME/swh-environment/swh-objstorage:/src/swh-objstorage:ro"

The file named ``compose.override.yml`` will automatically be loaded by Docker
Compose if no ``--file`` argument is set nor the ``COMPOSE_FILE`` environment
variable is defined (otherwise you have to add it explicitly).

This example shows the simple case of the ``swh-objstorage`` package: the local
``swh-objstorage`` source code repository is mounted in the container in
``/src``. The entrypoint will detect this and install it using pip in editable
mode (as well as any other swh-\* package found in ``/src/``) so you can easily
hack your code. If the application you play with has autoreload support, there
is no need to restart the impacted container (this may not always work).


In a nutshell
-------------

-  Start the SWH platform:

   .. code-block:: console

     (swh) ~/swh-environment$ docker compose up -d
     [...]

-  Check celery:

   .. code-block:: console

     (swh) ~/swh-environment$ docker compose exec swh-scheduler \
       celery status
     listers@50ac2185c6c9: OK
     loader@b164f9055637: OK
     indexer@33bc6067a5b8: OK

-  List task-types:

   .. code-block:: console

     (swh) ~/swh-environment$ docker compose exec swh-scheduler \
       swh scheduler task-type list
     [...]

-  Get more info on a task type:

   .. code-block:: console

     (swh) ~/swh-environment$ docker compose exec swh-scheduler \
       swh scheduler task-type list -v -t load-hg
     Known task types:
     load-hg: swh.loader.mercurial.tasks.LoadMercurial
       Loading mercurial repository swh-loader-mercurial
       interval: 1 day, 0:00:00 [1 day, 0:00:00, 1 day, 0:00:00]
       backoff_factor: 1.0
       max_queue_length: 1000
       num_retries: None
       retry_delay: None

-  Add a new task:

   .. code-block:: console

     (swh) ~/swh-environment$ docker compose exec swh-scheduler \
       swh scheduler task add load-hg \
       url=https://www.mercurial-scm.org/repo/hello
     Created 1 tasks
     Task 1
        Next run: just now (2019-02-06 12:36:58+00:00)
        Interval: 1 day, 0:00:00
        Type: load-hg
        Policy: recurring
        Args:
        Keyword args:
          url: https://www.mercurial-scm.org/repo/hello

-  Respawn a task:

   .. code-block:: console

     (swh) ~/swh-environment$ docker compose exec swh-scheduler \
       swh scheduler task respawn 1

Using locally installed swh tools with docker
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In all examples above, we have executed swh commands from within a running
container. It is sometimes easily possible to run them locally, in your virtual
env. If you have a virtualenv with the swh stack properly installed, you can
use them to interact with swh services running in docker containers.

For this, we just need to configure a few environment variables. First,
ensure your Software Heritage virtualenv is activated (here, using
virtualenvwrapper):

.. code-block:: console

   ~$ workon swh
   (swh) ~/swh-environment$ export NGINX_PORT=$(docker compose port nginx 80 | awk -F ':' '{print$2}')
   (swh) ~/swh-environment$ export SWH_SCHEDULER_URL=http://127.0.0.1:${NGINX_PORT}/rpc/scheduler/

You can now use the ``swh-scheduler`` command directly from your working venv:

.. code-block:: console

   (swh) ~/swh-environment$ swh scheduler task-type list
   Known task types:
   index-fossology-license:
     Fossology license indexer task
   index-mimetype:
     Mimetype indexer task
   [...]


.. _docker-persistence:

Data persistence for a development setting
------------------------------------------

The default ``compose.yml`` configuration is not geared towards
data persistence, but application testing.

Volumes defined in associated images are anonymous and may get either
unused or removed on the next ``docker compose up``.

One way to make sure these volumes persist is to use named volumes. The
volumes may be defined as follows in a ``compose.override.yml``.
Note that volume definitions are merged with other compose files based
on destination path.

::

   services:
     swh-storage-db:
       volumes:
         - "swh_storage_data:/var/lib/postgresql/data"
     swh-objstorage:
       volumes:
         - "swh_objstorage_data:/srv/softwareheritage/objects"

   volumes:
     swh_storage_data:
     swh_objstorage_data:

This way, ``docker compose down`` without the ``-v`` flag will not
remove those volumes and data will persist.


Additional components
---------------------

We provide some extra modularity in what components to run through
additional ``compose.*.yml`` files.

They are disabled by default, because they add layers of complexity
and increase resource usage, while not being necessary to operate
a small Software Heritage instance.

Starting a kafka-powered mirror of the storage
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This repo comes with an optional ``compose.storage-mirror.yml``
docker compose file that can be used to test the kafka-powered mirror
mechanism for the main storage.

This can be used like::

   ~/swh-environment/docker$ docker compose \
        -f compose.yml \
        -f compose.storage-mirror.yml \
        up -d
   [...]

Compared to the original compose file, this will:

-  overrides the swh-storage service to activate the kafka direct writer
   on swh.journal.objects prefixed topics using the swh.storage.master
   ID,
-  overrides the swh-web service to make it use the mirror instead of
   the master storage,
-  starts a db for the mirror,
-  starts a storage service based on this db,
-  starts a replayer service that runs the process that listen to kafka
   to keeps the mirror in sync.

When using it, you will have a setup in which the master storage is used
by workers and most other services, whereas the storage mirror will be
used to by the web application and should be kept in sync with the
master storage by kafka.

Note that the object storage is not replicated here, only the graph
storage.

Starting the backfiller
"""""""""""""""""""""""

Reading from the storage the objects from within range [start-object,
end-object] to the kafka topics.

::

   ~/swh-environment/docker$ docker compose \
        -f compose.yml \
        -f compose.storage-mirror.yml \
        -f compose.storage-mirror.override.yml \
        run \
        swh-journal-backfiller \
        snapshot \
        --start-object 000000 \
        --end-object 000001 \
        --dry-run

Cassandra
^^^^^^^^^

We are working on an alternative backend for swh-storage, based on Cassandra
instead of PostgreSQL.

This can be used like::

   ~/swh-environment/docker$ docker compose \
        -f compose.yml \
        -f compose.cassandra.yml \
        up -d
   [...]


This launches two Cassandra servers, and reconfigures swh-storage to use them.

Efficient origin search
^^^^^^^^^^^^^^^^^^^^^^^

By default, swh-web uses swh-storage and swh-indexer-storage to provide its
search bar. They are both based on PostgreSQL and rather inefficient
(or Cassandra, which is even slower).

Instead, you can enable swh-search, which is based on ElasticSearch
and much more efficient, like this::

   ~/swh-environment/docker$ docker compose \
        -f compose.yml \
        -f compose.search.yml \
        up -d
   [...]

Efficient counters
^^^^^^^^^^^^^^^^^^

The web interface shows counters of the number of objects in your archive,
by counting objects in the PostgreSQL or Cassandra database.

While this should not be an issue at the scale of your local Docker instance,
counting objects can actually be a bottleneck at Software Heritage's scale.
So swh-storage uses heuristics, that can be either not very efficient
or inaccurate.

So we have an alternative based on Redis' HyperLogLog feature, which you
can test with::

   ~/swh-environment/docker$ docker compose \
        -f compose.yml \
        -f compose.counters.yml \
        up -d
   [...]


Efficient graph traversals
^^^^^^^^^^^^^^^^^^^^^^^^^^

:ref:`swh-graph <swh-graph>` is a work-in-progress alternative to swh-storage
to perform large graph traversals/queries on the merkle DAG.

For example, it can be used by the vault, as it needs to query all objects
in the sub-DAG of a given node.

You can use it with::

   ~/swh-environment/docker$ docker compose \
       -f compose.yml \
       -f compose.graph.yml up -d

On the first start, it will run some precomputation based on all objects already
in your local SWH instance; so it may take a long time if you loaded many
repositories. (Expect 5 to 10s per repository.)

It **does not update automatically** when you load new repositories.
You need to restart it every time you want to update it.

You can :ref:`mount a docker volume <docker-persistence>` on
:file:`/srv/softwareheritage/graph` to avoid recomputing this graph
on every start.
Then, you need to explicitly request recomputing the graph before restarts
if you want to update it::

   ~/swh-environment/docker$ docker compose \
        -f compose.yml \
        -f compose.graph.yml \
        run swh-graph update
   ~/swh-environment/docker$ docker compose \
        -f compose.yml \
        -f compose.graph.yml \
        stop swh-graph
   ~/swh-environment/docker$ docker compose \
        -f compose.yml \
        -f compose.graph.yml \
        up -d swh-graph


Keycloak
^^^^^^^^

If you really want to hack on swh-web's authentication features,
you will need to enable Keycloak as well, instead of the default
Django-based authentication::

   ~/swh-environment/docker$ docker compose -f compose.yml -f compose.keycloak.yml up -d
   [...]

User registration in Keycloak database is available by following the Register link
in the page located at http://localhost:<publicport>/oidc/login/.

Please note that email verification is required to properly register an account.
As we are in a testing environment, we use a Mailpit instance as a fake SMTP server.
All emails sent by Keycloak can be easily read from the Mailpit Web UI located
at http://localhost:8025/.


Kafka
^^^^^

Consuming topics from the host
""""""""""""""""""""""""""""""

As mentioned above, it is possible to consume topics from the kafka server available
in the Docker Compose environment from the host using `127.0.0.1:5092` as broker URL.

Resetting offsets
"""""""""""""""""

It is also possible to reset a consumer group offset using the following command::

  ~swh-environment/docker$ docker compose \
       run kafka kafka-consumer-groups.sh \
           --bootstrap-server kafka:9092 \
           --group <group> \
           --all-topics \
           --reset-offsets --to-earliest --execute
  [...]

You can use `--topic <topic>` instead of `--all-topics` to specify a topic.

Getting information on consumers
""""""""""""""""""""""""""""""""

You can get information on consumer groups::

  ~swh-environment/docker$ docker compose \
       run kafka kafka-consumer-groups.sh \
           --bootstrap-server kafka:9092 \
           --describe --members --all-groups
  [...]

Or the stored offsets for all (or a given) groups::

  ~swh-environment/docker$ docker compose \
       run kafka kafka-consumer-groups.sh \
           --bootstrap-server kafka:9092 \
           --describe --offsets --all-groups
  [...]


Using Sentry
------------

All entrypoints to SWH code (CLI, gunicorn, celery, …) are, or should
be, instrumented using Sentry. By default this is disabled, but if you
run your own Sentry instance, you can use it.

To do so, you must get a DSN from your Sentry instance, and set it as
the value of ``SWH_SENTRY_DSN`` in the file ``env/common_python.env``.
You may also set it per-service in the ``environment`` section of each
services in ``compose.override.yml``.

Caveats
-------

Running a lister task can lead to a lot of loading tasks, which can fill
your hard drive pretty fast. Make sure to monitor your available storage
space regularly when playing with this stack.

Also, a few containers (``swh-storage``, ``swh-xxx-db``) use a volume
for storing the blobs or the database files. With the default
configuration provided in the ``compose.yml`` file, these volumes
are not persistent. So removing the containers will delete the volumes!

Also note that for the ``swh-objstorage``, since the volume can be
pretty big, the remove operation can be quite long (several minutes is
not uncommon), which may mess a bit with the ``docker compose`` command.

If you have an error message like:

Error response from daemon: removal of container 928de3110381 is already
in progress

it means that you need to wait for this process to finish before being
able to (re)start your docker stack again.
