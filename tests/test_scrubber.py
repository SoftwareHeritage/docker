# Copyright (C) 2023-2024  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

import json
from typing import List

import pytest

from .conftest import compose_host_for_service


@pytest.fixture(scope="module")
def compose_files() -> List[str]:
    # overload the default list to add scrubber compose override
    return ["compose.yml", "compose.scrubber.yml"]


def test_scrubber_check(docker_compose, origins):
    # start the scrubber service (the compose file does not start it up, it
    # just defines it)
    docker_compose.check_compose_output(
        "up --scale swh-scrubber=1  --no-recreate --wait swh-scrubber"
    )
    scrubber = compose_host_for_service(docker_compose, "swh-scrubber")

    # configure a scrubbing session for snapshots using 16 partitions
    scrubber.check_output(
        "swh scrubber check init storage "
        "--object-type snapshot "
        "--nb-partitions 16 "
        "--name snapshot_4 "
    )

    # check we have the expected scrubbing configuration registered
    expected = (
        "[1] snapshot_4: snapshot, 16, storage:postgresql "
        "(postgresql:///?service=swh-storage)"
    )
    cfg_lst = scrubber.check_output("swh scrubber check list")
    assert expected in cfg_lst, cfg_lst

    # run the scrubbing session using one worker
    scrubber.check_output("swh scrubber check storage snapshot_4")

    # check the scrubbing session has checked all the snapshot partitions
    stats = json.loads(scrubber.check_output("swh scrubber check stats snapshot_4 -j"))

    assert stats["config"]["name"] == "snapshot_4"
    assert stats["config"]["object_type"] == "snapshot"
    assert stats["config"]["nb_partitions"] == 16

    assert stats["checked_partition"] == 16
    assert stats["corrupt_object"] == 0
    assert stats["missing_object"] == 0

    # alter the content of the storage...
    # xx

    # reset the scrubbing session and rerun it
    # xx

    # check the stats for found errors
    # xx
