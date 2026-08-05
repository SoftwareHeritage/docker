# Copyright (C) 2019-2025  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

import atexit
import logging
import os
import shutil
import time
from functools import partial
from subprocess import CalledProcessError, check_output
from typing import Iterable, List, Set, Tuple, Union
from uuid import uuid4 as uuid

import pytest
import requests
import testinfra
import yaml

from .utils import api_get as api_get_func
from .utils import api_get_directory as api_get_directory_func
from .utils import api_poll as api_poll_func
from .utils import compose_host_for_service, filter_origins, retry_until_success

logger = logging.getLogger(__name__)

# wait-for-it timeout
WFI_TIMEOUT = 120


def pytest_collection_modifyitems(config, items):
    """Tests for swh-environment require docker compose (v2 or v1) so skip them
    if it is not installed on host."""
    skipper = None
    if shutil.which("docker") is None:
        skipper = pytest.mark.skip(reason="skipping test as docker command is missing")
    else:
        docker_compose_available = False
        try:
            # check if docker compose v2 if available
            check_output(["docker", "compose", "version"])
            docker_compose_available = True
        except CalledProcessError:
            # check if docker compose v1 if available
            docker_compose_available = shutil.which("docker-compose") is not None
        finally:
            if not docker_compose_available:
                skipper = pytest.mark.skip(
                    reason="skipping test as docker compose is missing"
                )
    if skipper is not None:
        for item in items:
            item.add_marker(skipper)


def pytest_addoption(parser):
    parser.addoption(
        "--use-compose-override",
        action="store_true",
        help=(
            "Include compose.override.yml file in each compose files list "
            "used by tests, useful for tests development"
        ),
    )


@pytest.fixture(scope="session")
def docker_host():
    return testinfra.get_host("local://")


@pytest.fixture(scope="module")
def compose_files() -> List[str]:
    # this fixture is meant to be overloaded in test modules to include the
    # required compose files for the test (see test_deposit.py for example)
    return ["compose.yml"]


@pytest.fixture(scope="module")
def defined_compose_services(compose_files) -> Set[str]:
    services = set()
    for compose_file in compose_files:
        with open(compose_file, "r") as compose_fd:
            compose_data = yaml.safe_load(
                compose_fd.read().replace("!override", "").replace("!reset", "")
            )
            services.update(compose_data["services"].keys())
    return services


@pytest.fixture(scope="module")
def compose_services() -> List[str]:
    # this fixture is meant to be overloaded in test modules to explicitly
    # specify which services to spawn in the docker compose session.
    # If empty (the default), spawn all the services defined in the compose files.
    return []


@pytest.fixture(scope="session")
def project_name() -> str:
    return f"swh_test_{uuid()}"


@pytest.fixture(scope="module")
def compose_cmd(docker_host, project_name, compose_files, pytestconfig):
    compose_override = "compose.override.yml"
    if (
        pytestconfig.getoption("--use-compose-override")
        and compose_override not in compose_files
        and os.path.isfile(compose_override)
    ):
        compose_files.append(compose_override)
    print(f"COMPOSE_PROJECT_NAME={project_name}", end=" ")
    print(f"COMPOSE_FILE={':'.join(compose_files)}")
    compose_file_cmd = "".join(f" -f {fname} " for fname in compose_files)
    try:
        docker_host.check_output("docker compose version")
        return f"docker compose -p {project_name} {compose_file_cmd} "
    except AssertionError:
        print("Fall back to old docker-compose command")
        return f"docker-compose -p {project_name} {compose_file_cmd} "


def stop_compose_session(docker_host, project_name):
    print(f"\nStopping the compose session {project_name}...", end=" ", flush=True)
    # first kill all the containers (brutal but much faster than a proper shutdown)
    containers = docker_host.check_output(
        f"docker compose -p {project_name} ps -q"
    ).replace("\n", " ")
    if containers:
        try:
            docker_host.check_output(f"docker kill {containers}")
        except AssertionError:
            # may happen if a container is killed as a result of another one
            # being shut down...
            pass
        # and gently stop the cluster
        docker_host.check_output(
            f"docker compose -p {project_name} down --volumes --remove-orphans"
        )
        print("OK")
        retry_until_success(
            lambda: not docker_host.check_output(
                f"docker compose -p {project_name} ps -q"
            ),
            error_message="Failed to shut compose down",
            max_attempts=30,
        )
        print("... All the services are stopped")


@pytest.fixture(scope="session", autouse=True)
def compose_session_cleaner(docker_host, project_name):
    # register an exit handler to ensure started containers will be stopped, even
    # if any keyboard interruption or unhandled exception occurs
    atexit.register(stop_compose_session, docker_host, project_name)


@pytest.fixture(scope="module")
def reset_compose_session():
    # by default all compose services are restarted from scratch when processing
    # a test module.

    # nevertheless, if the compose environment for a test module does not require
    # a full reset (services restart and empty volumes), that fixture can be overridden
    # in the test module so that it returns False, only orphan compose services are
    # shut down in that case
    return True


# scope='module' so we use the same container for all the tests in a test file
@pytest.fixture(scope="module")
def docker_compose(
    request,
    docker_host,
    project_name,
    compose_cmd,
    compose_services,
    tmp_path_factory,
    defined_compose_services,
    reset_compose_session,
):
    failed_tests_count = request.node.session.testsfailed
    got_exception = False

    if reset_compose_session:
        stop_compose_session(docker_host, project_name)

    if hasattr(docker_host, "check_compose_output"):
        # nginx service must be restarted when executing test modules
        # sequentially or 502 and 504 errors can happen otherwise
        docker_host.check_compose_output("stop nginx")

    print(f"Starting the compose session {project_name} ...", end=" ", flush=True)
    t = time.time()
    try:
        # pull required docker images
        docker_host.check_output(f"{compose_cmd} pull --ignore-pull-failures")

        # start the whole cluster
        for i in range(3):
            try:
                docker_host.check_output(
                    f"{compose_cmd} up --wait -d {' '.join(compose_services)}"
                )
                break
            except Exception as exc:
                print(f"Failed to converge ({exc})")
                if i == 2:
                    print("Giving up!")
                    raise
                else:
                    print("Retrying...")

        print("OK")

        if hasattr(docker_host, "check_compose_output"):
            # kill orphan services from previous test module execution
            services = set(
                docker_host.check_compose_output("ps --services").splitlines()
            )
            services_to_kill = [
                service
                for service in services
                if service not in defined_compose_services
            ]
            if services_to_kill:
                print("Killing orphan services: ", ", ".join(services_to_kill))
                docker_host.check_compose_output(f"kill {' '.join(services_to_kill)}")

        elapsed = time.time() - t

        # small hack: add a helper func to docker_host; so it's not necessary to
        # use all 3 docker_compose, docker_host and compose_cmd fixtures everywhere
        docker_host.check_compose_output = lambda command: docker_host.check_output(
            f"{compose_cmd} {command}"
        )
        services = set(docker_host.check_compose_output("ps --services").splitlines())
        print(f"Started {len(services)} services in {elapsed:.2f}s")

        yield docker_host
    except Exception:
        got_exception = True
        raise
    finally:
        if got_exception or request.node.session.testsfailed != failed_tests_count:
            logs_filename = request.node.name.replace(".py", ".logs")
            logs_dir = os.path.join(tmp_path_factory.getbasetemp(), "docker")
            os.makedirs(logs_dir, exist_ok=True)
            logs_filepath = os.path.join(logs_dir, logs_filename)
            print(
                f"Tests failed in {request.node.name}, "
                f"dumping logs to {logs_filepath}"
            )
            services = docker_host.check_output(f"{compose_cmd} ps --services --all")
            for service in services.splitlines():
                try:
                    logs = docker_host.check_output(f"{compose_cmd} logs -t {service}")
                except Exception:
                    # some services might no longer exist, ignore them
                    pass
                else:
                    with open(logs_filepath, "a") as logs_file:
                        logs_file.write(logs)


def service_port(docker_compose_host, service, port=80) -> int:
    port_output = docker_compose_host.check_compose_output(f"port {service} {port}")
    return int(port_output.split(":")[1])


def service_url(
    docker_compose_host, service, docker_network_gateway_ip, port=80
) -> str:
    bound_port = service_port(docker_compose_host, service, port)
    # as tests could be executed inside a container, we use the docker bridge
    # network gateway ip instead of localhost domain name
    return f"http://{docker_network_gateway_ip}:{bound_port}"


@pytest.fixture(scope="module")
def nginx_url(docker_compose, docker_network_gateway_ip) -> str:
    return service_url(docker_compose, "nginx", docker_network_gateway_ip)


@pytest.fixture(scope="module")
def api_url(nginx_url) -> str:
    return f"{nginx_url}/api/1/"


@pytest.fixture(scope="module")
def kafka_api_url(nginx_url) -> str:
    return f"{nginx_url}/kafka/v3/clusters"


@pytest.fixture(scope="module")
def docker_network_gateway_ip(docker_compose):
    docker_helper = compose_host_for_service(docker_compose, "docker-helper")
    return docker_helper.check_output("curl -s http://localhost/gateway/")


@pytest.fixture(scope="module")
def scheduler_host(docker_compose):
    # run a container in which test commands are executed
    scheduler_host = compose_host_for_service(docker_compose, "swh-scheduler")
    assert scheduler_host
    scheduler_host.check_output(f"wait-for-it swh-storage:5002 -t {WFI_TIMEOUT}")
    # return a testinfra connection to the container
    yield scheduler_host


@pytest.fixture(scope="module")
def loader_host(docker_compose):
    # run a container in which test commands are executed
    loader_host = compose_host_for_service(docker_compose, "swh-loader")
    assert loader_host
    loader_host.check_output(f"wait-for-it swh-storage:5002 -t {WFI_TIMEOUT}")
    # return a testinfra connection to the container
    yield loader_host


@pytest.fixture(scope="module")
def lister_host(docker_compose):
    # run a container in which test commands are executed
    lister_host = compose_host_for_service(docker_compose, "swh-lister")
    assert lister_host
    lister_host.check_output(f"wait-for-it swh-scheduler:5008 -t {WFI_TIMEOUT}")
    # return a testinfra connection to the container
    yield lister_host


@pytest.fixture(scope="module")
def http_session():
    with requests.Session() as session:
        yield session


@pytest.fixture(scope="module")
def nginx_get(nginx_url, http_session):
    return partial(api_get_func, nginx_url, session=http_session)


@pytest.fixture(scope="module")
def api_get(api_url, http_session):
    return partial(api_get_func, api_url, session=http_session)


@pytest.fixture(scope="module")
def api_poll(api_url, http_session):
    return partial(api_poll_func, api_url, session=http_session)


@pytest.fixture(scope="module")
def api_get_directory(api_url, http_session):
    return partial(api_get_directory_func, api_url, session=http_session)


@pytest.fixture(scope="module")
def webapp_host(docker_compose):
    webapp_host = compose_host_for_service(docker_compose, "swh-web")
    assert webapp_host
    webapp_host.check_output(f"wait-for-it swh-storage:5002 -t {WFI_TIMEOUT}")

    # return a testinfra connection to the container
    yield webapp_host


@pytest.fixture(scope="module")
def small_git_repo():
    return "https://gitlab.softwareheritage.org/swh/devel/swh-counters.git"


@pytest.fixture(scope="module")
def tiny_git_repo():
    return "https://gitlab.softwareheritage.org/swh/devel/swh-py-template.git"


@pytest.fixture(scope="module")
def origin_urls(tiny_git_repo) -> List[Tuple[str, Union[str, Iterable[str]]]]:
    # This fixture is meant to be overloaded in test modules to initialize the
    # main storage with the content from the loading of the origins listed
    # here. By default we only load one git origin (to try to keep execution
    # time under control), but some tests may require more than that.
    return [("git", tiny_git_repo)]


@pytest.fixture(scope="module")
def origins(loader_host, origin_urls: List[Tuple[str, str]]):
    """A fixture that ingest origins from origin_urls in the storage"""
    origin_urls = [(otype, filter_origins(urls)) for (otype, urls) in origin_urls]

    for origin_type, origin_url in origin_urls:
        print(f"Loading {origin_type} origin: {origin_url}")
        t = time.time()
        loader_host.check_output(
            f"swh loader run {origin_type.replace('hg', 'mercurial')} {origin_url}"
        )
        elapsed = time.time() - t
        print(f"Loading of {origin_url} took {elapsed:.2f}s")

    return origin_urls


@pytest.fixture
def smtp_port(docker_compose):
    """Get the port exposed by our smtp server."""
    return service_port(docker_compose, "smtp4tests", 1025)


@pytest.fixture(scope="module")
def alter_host(docker_compose) -> Iterable[testinfra.host.Host]:
    # Getting a compressed graph with swh-graph is not stable enough
    # so we use a mock server for the time being that starts
    # by default when running the swh-alter container.
    for i in range(10):
        docker_id = docker_compose.check_compose_output(
            "ps --status running --format '{{.Name}}' swh-alter"
        ).strip()
        if docker_id:
            break
        time.sleep(5)

    host = testinfra.get_host("docker://" + docker_id)
    host.check_output("wait-for-it --timeout=60 swh-alter:5009")
    yield host


@pytest.fixture(scope="module")
def storage_public_service(docker_compose):
    return compose_host_for_service(docker_compose, "swh-storage-public")
