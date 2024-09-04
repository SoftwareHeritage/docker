# Copyright (C) 2023-2024  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

import dataclasses
import hashlib
import logging
import random
from typing import Iterable, List, Optional, Tuple

import pytest
import requests
import testinfra
import yaml

from .utils import retry_until_success

logger = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def compose_files() -> List[str]:
    return ["compose.yml", "compose.search.yml", "compose.alter.yml"]


@pytest.fixture(scope="module")
def compose_services() -> List[str]:
    return [
        "docker-helper",
        "docker-proxy",
        "swh-alter",
        "swh-search",
        "swh-search-journal-client-objects",
        "swh-search-journal-client-indexed",
        "swh-storage",
        "swh-objstorage",
        "swh-storage-replayer",
        "swh-extra-objstorage",
        "swh-objstorage-replayer",
        "swh-scheduler-runner",
        "swh-scheduler-listener",
        "swh-scheduler-schedule-recurrent",
        "swh-web",
        "swh-loader",
        "swh-lister",
    ]


@pytest.fixture(scope="module")
def origin_urls(tiny_git_repo) -> List[Tuple[str, str]]:
    return [
        tiny_git_repo,
        ("git", "https://gitlab.softwareheritage.org/lunar/swh-py-template.git"),
    ]


@pytest.fixture(scope="module")
def alter_host(docker_compose) -> Iterable[testinfra.host.Host]:
    # Getting a compressed graph with swh-graph is not stable enough
    # so we use a mock server for the time being that starts
    # by default when running the swh-alter container.
    docker_services = docker_compose.check_compose_output(
        "ps --status running --format '{{.Service}} {{.Name}}'"
    )
    docker_id = dict(line.split(" ") for line in docker_services.split("\n"))[
        "swh-alter"
    ]
    host = testinfra.get_host("docker://" + docker_id)
    host.check_output("wait-for-it --timeout=60 swh-alter:5009")
    yield host


def wait_for_replayer(docker_compose, kafka_api_url):
    # wait until the replayer is done
    print("Waiting for the replayer to be done")
    cluster = requests.get(kafka_api_url).json()["data"][0]["cluster_id"]

    def kget(path):
        url = f"{kafka_api_url}/{cluster}/{path}"
        resp = requests.get(url)
        if resp.status_code == 200:
            return resp.json()
        resp.raise_for_status()

    for consumer in (
        "swh.alter.storage.replayer",
        "swh.alter.objstorage.replayer",
        "swh.search.journal_client",
    ):

        def check_consumer_finished_job():
            try:
                lag_sum = kget(f"consumer-groups/{consumer}/lag-summary")
            except requests.exceptions.HTTPError as exc:
                print(f"Failed to retrieve consumer status: {exc}")
                return False
            else:
                return lag_sum["total_lag"] == 0

        retry_until_success(
            check_consumer_finished_job,
            error_message=(
                "Could not detect a condition where the "
                f"consumer {consumer} did its job"
            ),
            max_attempts=30,
        )


@pytest.fixture(scope="module")
def verified_origins(alter_host, docker_compose, origins, kafka_api_url):
    # Verify that our origins have properly been loaded in PostgreSQL
    # and Cassandra
    origin_swhids = {
        f"swh:1:ori:{hashlib.sha1(url.encode('us-ascii')).hexdigest()}"
        for _, url in origins
    }
    docker_compose.check_compose_output(
        "exec swh-alter python /src/alter_companion.py "
        f"query-postgresql --presence {' '.join(origin_swhids)}"
    )

    docker_compose.check_compose_output(
        "exec swh-alter python /src/alter_companion.py "
        f"query-kafka --presence {' '.join(origin_swhids)}"
    )

    wait_for_replayer(docker_compose, kafka_api_url)

    return origins


@dataclasses.dataclass
class RemovalOperation:
    identifier: str
    bundle_path: str
    origins: List[str]
    removed_swhids: List[str] = dataclasses.field(default_factory=list)
    referencing: List[str] = dataclasses.field(default_factory=list)
    _removed_content_sha1s: Optional[List[bytes]] = None

    def get_removed_content_sha1s(self, host):
        if self._removed_content_sha1s is None:
            self._removed_content_sha1s = []
            # Computing the SHA1 of content objects from the recovery bundle
            # is a very slow operation. So let’s only take a random sample
            # of the content SWHIDS.
            some_content_swhids = random.sample(
                [
                    swhid
                    for swhid in self.removed_swhids
                    if swhid.startswith("swh:1:cnt:")
                ],
                k=5,
            )
            logger.debug(
                "random content sha1s picked %s", ", ".join(some_content_swhids)
            )
            for swhid in some_content_swhids:
                cmd = host.run(
                    f"swh alter recovery-bundle extract-content "
                    "--identity /srv/softwareheritage/age-identities.txt --output - "
                    f"'{self.bundle_path}' '{swhid}'"
                )
                assert cmd.succeeded, f"extract-content failed! {cmd.stderr}"
                sha1 = hashlib.sha1(cmd.stdout_bytes).hexdigest()
                logger.debug("%s data SHA1: %s", swhid, sha1)
                self._removed_content_sha1s.append(sha1)
        return self._removed_content_sha1s

    def run_in(self, host):
        remove_output = host.check_output(
            "echo y | swh alter remove "
            f"--identifier '{self.identifier}' "
            f"--recovery-bundle '{self.bundle_path}' "
            f"{' '.join(self.origins)}"
        )
        logger.debug(remove_output)
        dump = host.check_output(
            f"swh alter recovery-bundle info --dump-manifest '{self.bundle_path}'"
        )
        manifest = yaml.safe_load(dump)
        logger.debug("%s manifest %s", self.identifier, manifest)
        self.removed_swhids = manifest["swhids"]
        if int(manifest["version"]) >= 3:
            assert self.origins == manifest["requested"]
            self.referencing = manifest["referencing"]


FORK_REMOVAL_OP = RemovalOperation(
    identifier="integration-test-fork",
    bundle_path="/tmp/integration-test-fork.swh-recovery-bundle",
    origins=["https://gitlab.softwareheritage.org/lunar/swh-py-template.git"],
)


@pytest.fixture(scope="module")
def fork_removed(alter_host, verified_origins):
    FORK_REMOVAL_OP.run_in(alter_host)
    assert len(FORK_REMOVAL_OP.removed_swhids) > 0
    return FORK_REMOVAL_OP


def test_fork_removed_in_postgresql(docker_compose, fork_removed):
    # Ensure the SWHIDs have been removed from PostgreSQL
    docker_compose.check_compose_output(
        "exec swh-alter python /src/alter_companion.py "
        f"query-postgresql {' '.join(fork_removed.removed_swhids)}"
    )


def test_fork_removed_in_cassandra(docker_compose, fork_removed):
    # Ensure the SWHIDs have been removed from Cassandra
    docker_compose.check_compose_output(
        "exec swh-alter python /src/alter_companion.py "
        f"query-cassandra {' '.join(fork_removed.removed_swhids)}"
    )


def test_fork_removed_in_kafka(docker_compose, fork_removed):
    # Ensure the SWHIDs have been removed from Kafka
    docker_compose.check_compose_output(
        "exec swh-alter python /src/alter_companion.py "
        f"query-kafka {' '.join(fork_removed.removed_swhids)}"
    )


def test_fork_removed_in_elasticsearch(docker_compose, fork_removed):
    # Ensure the origins have been removed from ElasticSearch
    docker_compose.check_compose_output(
        "exec swh-alter python /src/alter_companion.py "
        f"query-elasticsearch {' '.join(fork_removed.origins)}"
    )


@pytest.fixture(scope="module")
def fork_restored(fork_removed, alter_host, docker_compose, kafka_api_url):
    alter_host.check_output(
        f"swh alter recovery-bundle restore '{fork_removed.bundle_path}' "
        "--identity /srv/softwareheritage/age-identities.txt"
    )
    wait_for_replayer(docker_compose, kafka_api_url)
    return fork_removed


def test_fork_restored_in_postgresql(docker_compose, fork_restored):
    # Ensure the SWHIDs are back in PostgreSQL
    docker_compose.check_compose_output(
        "exec swh-alter python /src/alter_companion.py "
        f"query-postgresql --presence {' '.join(fork_restored.removed_swhids)}"
    )


def test_fork_restored_in_cassandra(docker_compose, fork_restored):
    # Ensure the SWHIDs are back in Cassandra (through the replayer)
    docker_compose.check_compose_output(
        "exec swh-alter python /src/alter_companion.py "
        f"query-cassandra --presence {' '.join(fork_restored.removed_swhids)}"
    )


def test_fork_restored_in_kafka(docker_compose, fork_restored):
    # Ensure the SWHIDs are back in Kafka
    docker_compose.check_compose_output(
        "exec swh-alter python /src/alter_companion.py "
        f"query-kafka --presence {' '.join(fork_restored.removed_swhids)}"
    )


def test_fork_restored_in_elasticsearch(docker_compose, fork_restored):
    # Ensure the origins have been restored in ElasticSearch
    docker_compose.check_compose_output(
        "exec swh-alter python /src/alter_companion.py "
        f"query-elasticsearch --presence {' '.join(fork_restored.origins)}"
    )


@pytest.fixture(scope="module")
def initial_removed(alter_host, verified_origins, fork_restored, tiny_git_repo):
    initial_removal_op = RemovalOperation(
        identifier="integration-test-initial",
        bundle_path="/tmp/integration-test-initial.swh-recovery-bundle",
        origins=[tiny_git_repo[1]],
    )
    initial_removal_op.run_in(alter_host)
    assert len(initial_removal_op.removed_swhids) > 0
    return initial_removal_op


def test_initial_removed_in_primary_objstorage(
    docker_compose, initial_removed, alter_host
):
    # Ensure objects have been removed from primary objstorage
    docker_compose.check_compose_output(
        "exec swh-alter python /src/alter_companion.py query-objstorage "
        "--objstorage-url http://nginx/rpc/objstorage "
        f"{' '.join(initial_removed.get_removed_content_sha1s(alter_host))}"
    )


def test_initial_removed_in_extra_objstorage(
    docker_compose, initial_removed, alter_host
):
    # Ensure objects have been removed from extra objstorage
    docker_compose.check_compose_output(
        "exec swh-alter python /src/alter_companion.py query-objstorage "
        "--objstorage-url http://swh-extra-objstorage:5003 "
        f"{' '.join(initial_removed.get_removed_content_sha1s(alter_host))}"
    )


def test_fork_restored_initial_removed_fork_still_available(
    docker_compose, fork_restored, initial_removed
):
    # Please keep in mind that the removal operation for the fork was done
    # while initial was in storage and, likewise, the removal operation for the
    # initial project was done while the fork was in storage.
    removed_with_fork = set(fork_restored.removed_swhids)
    removed_with_initial = set(initial_removed.removed_swhids)
    referencing_with_fork = set(fork_restored.referencing)
    referencing_with_initial = set(initial_removed.referencing)
    # As the fork has been restored, no objects belonging to the fork should
    # have been removed:
    assert removed_with_fork.isdisjoint(removed_with_initial)
    # But they should be referencing objects from one another
    assert len(referencing_with_initial - referencing_with_fork) > 0
    assert len(referencing_with_fork - referencing_with_initial) > 0
    # The GPLv3 should not have been removed (as it is listed as never
    # removable in swh-alter) but referenced:
    assert "swh:1:cnt:94a9ed024d3859793618152ea559a168bbcbb5e2" not in removed_with_fork
    assert (
        "swh:1:cnt:94a9ed024d3859793618152ea559a168bbcbb5e2" not in removed_with_initial
    )
    assert "swh:1:cnt:94a9ed024d3859793618152ea559a168bbcbb5e2" in referencing_with_fork
    assert (
        "swh:1:cnt:94a9ed024d3859793618152ea559a168bbcbb5e2" in referencing_with_initial
    )


@pytest.fixture(scope="module")
def initial_restored(initial_removed, alter_host, docker_compose, kafka_api_url):
    alter_host.check_output(
        f"swh alter recovery-bundle restore '{initial_removed.bundle_path}' "
        "--identity /srv/softwareheritage/age-identities.txt"
    )
    wait_for_replayer(docker_compose, kafka_api_url)
    return initial_removed


def test_initial_restored_in_primary_objstorage(
    docker_compose, initial_restored, alter_host
):
    # Ensure objects are back in primary objstorage
    docker_compose.check_compose_output(
        "exec swh-alter python /src/alter_companion.py query-objstorage --presence "
        "--objstorage-url http://nginx/rpc/objstorage "
        f"{' '.join(initial_restored.get_removed_content_sha1s(alter_host))}"
    )


def test_initial_restored_in_extra_objstorage(
    docker_compose, initial_restored, alter_host
):
    # Ensure objects are back in extra objstorage (through the replayer)
    docker_compose.check_compose_output(
        "exec swh-alter python /src/alter_companion.py query-objstorage --presence "
        "--objstorage-url http://swh-extra-objstorage:5003 "
        f"{' '.join(initial_restored.get_removed_content_sha1s(alter_host))}"
    )


@pytest.fixture(scope="module")
def both_removed(
    alter_host, verified_origins, fork_restored, initial_restored, tiny_git_repo
):
    both_removal_op = RemovalOperation(
        identifier="integration-test-both",
        bundle_path="/tmp/integration-test-both.swh-recovery-bundle",
        origins=[
            tiny_git_repo[1],
            "https://gitlab.softwareheritage.org/lunar/swh-py-template.git",
        ],
    )
    both_removal_op.run_in(alter_host)
    assert len(both_removal_op.removed_swhids) > 0
    return both_removal_op


def test_remove_both_forks(
    docker_compose, fork_restored, initial_restored, both_removed
):
    removed_with_both = set(both_removed.removed_swhids)
    assert removed_with_both.issuperset(set(fork_restored.removed_swhids))
    assert removed_with_both.issuperset(set(initial_restored.removed_swhids))
    # The only object referenced should be on the never removable list:
    assert set(both_removed.referencing) == {
        # Empty content
        "swh:1:cnt:e69de29bb2d1d6434b8b29ae775ad8c2e48c5391",
        # GPLv3
        "swh:1:cnt:94a9ed024d3859793618152ea559a168bbcbb5e2",
        # Directory with empty __init__.py
        "swh:1:dir:9d1dcfdaf1a6857c5f83dc27019c7600e1ffaff8",
    }
