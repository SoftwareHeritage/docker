# Copyright (C) 2023-2025  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

import hashlib
import logging
from typing import List, Tuple

import pytest
import requests

from .utils import RemovalOperation, retry_until_success

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
        "swh-web",
        "swh-loader",
    ]


@pytest.fixture(scope="module")
def origin_urls() -> List[Tuple[str, str]]:
    return [
        ("git", "https://gitlab.softwareheritage.org/swh/devel/swh-py-template.git"),
        ("git", "https://gitlab.softwareheritage.org/lunar/swh-py-template.git"),
    ]


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


@pytest.fixture(scope="module")
def fork_removed(alter_host, verified_origins):
    op = RemovalOperation(
        identifier="integration-test-fork",
        bundle_path="/tmp/integration-test-fork.swh-recovery-bundle",
        origins=["https://gitlab.softwareheritage.org/lunar/swh-py-template.git"],
    )
    op.run_in(alter_host)
    assert len(op.removed_swhids) > 0
    return op


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
        origins=[tiny_git_repo],
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
    alter_host,
    verified_origins,
    fork_restored,
    initial_restored,
    tiny_git_repo,
):
    both_removal_op = RemovalOperation(
        identifier="integration-test-both",
        bundle_path="/tmp/integration-test-both.swh-recovery-bundle",
        origins=[
            tiny_git_repo,
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
