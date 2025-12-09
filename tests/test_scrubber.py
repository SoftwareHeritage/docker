# Copyright (C) 2023-2025  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

import json
import textwrap
from typing import List

import pytest

from .utils import compose_host_for_service


@pytest.fixture(scope="module")
def compose_files() -> List[str]:
    # overload the default list to add scrubber compose override
    return ["compose.yml", "compose.scrubber.yml"]


@pytest.fixture(scope="module")
def compose_services():
    return [
        "docker-helper",
        "docker-proxy",
        "swh-loader",
        "swh-scrubber",
    ]


@pytest.fixture(autouse=True)
def scrubber_service_init(docker_compose):
    # start the scrubber service (the compose file does not start it up, it
    # just defines it)
    docker_compose.check_compose_output(
        "up --scale swh-scrubber=1  --no-recreate --wait swh-scrubber"
    )


@pytest.fixture
def scrubber_service(docker_compose):
    return compose_host_for_service(docker_compose, "swh-scrubber")


@pytest.fixture
def storage_service(docker_compose):
    return compose_host_for_service(docker_compose, "swh-storage")


@pytest.fixture
def objstorage_service(docker_compose):
    return compose_host_for_service(docker_compose, "swh-objstorage")


def create_scrubber_config(
    scrubber_service, backend, obj_type, nb_partitions=1, check_references=False
):
    print(f"Creating the scrubber config for checking objects of type {obj_type}")
    config_name = f"{obj_type}_{nb_partitions}"
    check_init_cmd = (
        f"swh scrubber check init {backend} --object-type {obj_type} "
        f"--nb-partitions {nb_partitions} --name {config_name}"
    )
    if check_references:
        check_init_cmd += " --check-references"
    output = scrubber_service.check_output(check_init_cmd)
    assert output.startswith(f"Created configuration {config_name}")
    return config_name


def run_scrubber_with_config(
    scrubber_service,
    backend,
    config_name,
    obj_type,
    nb_partitions=1,
    use_journal=False,
):
    # check we have the expected scrubbing configuration registered
    cfg_lst = scrubber_service.check_output("swh scrubber check list")
    assert f"{config_name}: {obj_type}, {nb_partitions}" in cfg_lst, cfg_lst

    print(f"Starting a SWH {backend} scrubber with config {config_name}")
    run_cmd = f"swh scrubber check run {config_name}"
    if use_journal:
        run_cmd += " --use-journal"
    scrubber_service.check_output(run_cmd)

    # return scrubbing stats
    return json.loads(
        scrubber_service.check_output(f"swh scrubber check stats {config_name} -j")
    )


def test_storage_scrubber_check_snapshots_no_corruption(scrubber_service, origins):
    """Run storage scrubbing on non corrupted neither missing snapshot objects."""

    obj_type = "snapshot"
    nb_partitions = 16

    config_name = create_scrubber_config(
        scrubber_service,
        backend="storage",
        obj_type=obj_type,
        nb_partitions=nb_partitions,
    )

    stats = run_scrubber_with_config(
        scrubber_service,
        backend="storage",
        config_name=config_name,
        obj_type=obj_type,
        nb_partitions=nb_partitions,
    )

    assert stats["config"]["name"] == config_name
    assert stats["config"]["object_type"] == obj_type
    assert stats["config"]["nb_partitions"] == nb_partitions

    assert stats["checked_partition"] == nb_partitions
    assert stats["corrupt_object"] == 0
    assert stats["missing_object"] == 0


@pytest.fixture
def deleted_contents(storage_service):
    def run_storage_sql_query(query):
        return storage_service.check_output(f'psql service=swh-storage -t -c "{query}"')

    nb_contents = int(run_storage_sql_query("SELECT count(*) FROM content"))

    assert nb_contents

    run_storage_sql_query("CREATE TABLE content_backup AS TABLE content")

    # remove all contents from storage
    run_storage_sql_query("TRUNCATE content")

    yield nb_contents

    run_storage_sql_query("INSERT INTO content (SELECT * FROM content_backup)")
    run_storage_sql_query("DROP TABLE content_backup")


def test_storage_scrubber_check_directory_missing_contents(
    scrubber_service,
    origins,
    deleted_contents,
):
    """Run storage scrubbing on directories referencing missing content objects."""

    obj_type = "directory"
    nb_partitions = 16

    # configure and run scrubbing
    config_name = create_scrubber_config(
        scrubber_service,
        backend="storage",
        obj_type=obj_type,
        nb_partitions=nb_partitions,
        check_references=True,
    )

    stats = run_scrubber_with_config(
        scrubber_service,
        backend="storage",
        config_name=config_name,
        obj_type=obj_type,
        nb_partitions=nb_partitions,
    )

    # check missing content objects were reported
    assert stats["config"]["name"] == config_name
    assert stats["config"]["object_type"] == obj_type
    assert stats["config"]["nb_partitions"] == nb_partitions

    assert stats["checked_partition"] == nb_partitions
    assert stats["corrupt_object"] == 0
    assert stats["missing_object"] == deleted_contents


def test_journal_scrubber_check_corrupt_snapshot(scrubber_service):
    # add corrupted snapshot to kafka snapshot topic in SWH journal
    script = """
    import attr
    import yaml
    from swh.journal.writer import get_journal_writer
    from swh.model.tests import swh_model_data
    with open("/srv/softwareheritage/config.yml", "r") as f:
        config = yaml.load(f.read(), yaml.SafeLoader)
    writer = get_journal_writer(
        cls="kafka", brokers=config["journal"]["brokers"],
        client_id="kafka_writer", prefix=config["journal"]["prefix"],
        anonymize=False
    )
    snapshot = list(swh_model_data.SNAPSHOTS)[0]
    snapshot = attr.evolve(snapshot, id=b"\\x00" * 20)
    writer.write_additions("snapshot", [snapshot])
    """
    scrubber_service.check_output(
        "cat << EOF >> /tmp/produce_corrupted_snapshot.py\n"
        f"{textwrap.dedent(script[1:])}\nEOF\n"
    )
    scrubber_service.check_output("python3 /tmp/produce_corrupted_snapshot.py")

    obj_type = "snapshot"
    nb_partitions = 1

    config_name = create_scrubber_config(
        scrubber_service,
        backend="journal",
        obj_type=obj_type,
        nb_partitions=nb_partitions,
    )

    stats = run_scrubber_with_config(
        scrubber_service,
        backend="journal",
        config_name=config_name,
        obj_type=obj_type,
        nb_partitions=nb_partitions,
    )

    assert stats["config"]["name"] == config_name
    assert stats["config"]["object_type"] == obj_type
    assert stats["corrupt_object"] == 1
    assert stats["missing_object"] == 0


@pytest.fixture
def corrupted_objstorage(objstorage_service):
    objects_dirs = objstorage_service.check_output(
        "ls /srv/softwareheritage/objects | sort -R | head -2"
    ).splitlines()

    nb_missing_contents = int(
        objstorage_service.check_output(
            f"ls -1q /srv/softwareheritage/objects/{objects_dirs[0]} | wc -l"
        )
    )

    objstorage_service.check_output(
        f"mv /srv/softwareheritage/objects/{objects_dirs[0]} /tmp"
    )

    nb_corrupted_contents = int(
        objstorage_service.check_output(
            f"ls -1q /srv/softwareheritage/objects/{objects_dirs[1]} | wc -l"
        )
    )

    objstorage_service.check_output(
        f"cp -r /srv/softwareheritage/objects/{objects_dirs[1]} /tmp/{objects_dirs[1]}"
    )

    objstorage_service.check_output(
        f"bash -c 'for f in /srv/softwareheritage/objects/{objects_dirs[1]}/*; "
        "do echo foo > $f; done'"
    )

    yield nb_missing_contents, nb_corrupted_contents

    objstorage_service.check_output(
        f"cp -r /tmp/{objects_dirs[0]} /srv/softwareheritage/objects/{objects_dirs[0]}"
    )
    objstorage_service.check_output(
        f"cp /tmp/{objects_dirs[1]}/* /srv/softwareheritage/objects/{objects_dirs[1]}/"
    )
    objstorage_service.check_output(f"rm -rf /tmp/{objects_dirs[0]}")
    objstorage_service.check_output(f"rm -rf /tmp/{objects_dirs[1]}")


def test_objstorage_partitions_scrubber_corrupted_and_missing_contents(
    corrupted_objstorage, scrubber_service, origins
):
    nb_missing_contents, nb_corrupted_contents = corrupted_objstorage

    obj_type = "content"
    nb_partitions = 16

    config_name = create_scrubber_config(
        scrubber_service, "objstorage", obj_type, nb_partitions
    )

    stats = run_scrubber_with_config(
        scrubber_service, "objstorage", config_name, obj_type, nb_partitions
    )

    assert stats["config"]["name"] == config_name
    assert stats["config"]["object_type"] == obj_type
    assert stats["config"]["nb_partitions"] == nb_partitions

    assert stats["checked_partition"] == nb_partitions
    assert stats["corrupt_object"] == nb_corrupted_contents
    assert stats["missing_object"] == nb_missing_contents


def test_objstorage_journal_scrubber_corrupted_and_missing_contents(
    corrupted_objstorage, scrubber_service, origins
):
    nb_missing_contents, nb_corrupted_contents = corrupted_objstorage

    obj_type = "content"

    config_name = create_scrubber_config(scrubber_service, "objstorage", obj_type)

    # in order for an objstorage scrubber to read content ids from a kafka topic,
    # the --use-journal flag of the "swh scrubber check run" command must be used
    stats = run_scrubber_with_config(
        scrubber_service, "objstorage", config_name, obj_type, use_journal=True
    )

    assert stats["config"]["name"] == config_name
    assert stats["config"]["object_type"] == obj_type

    assert stats["corrupt_object"] == nb_corrupted_contents
    assert stats["missing_object"] == nb_missing_contents
