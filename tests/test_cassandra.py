# Copyright (C) 2023  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

import re
from typing import List

import pytest

from .conftest import compose_host_for_service
from .test_git_loader import test_git_loader  # noqa


@pytest.fixture(scope="module")
def compose_files() -> List[str]:
    # overload the default list to add cassandra specific compose override
    return ["compose.yml", "compose.cassandra.yml"]


def test_ensure_cassandra(docker_compose, origins):
    check_output = docker_compose.check_compose_output
    # ensure the cassandra-seed service is running
    assert check_output("ps -q cassandra-seed")
    # ensure the swh-storage-db service does NOT exists
    services = check_output("ps")
    assert "swh-storage-db" not in services

    cass_host = compose_host_for_service(docker_compose, "cassandra-seed")
    assert cass_host
    # ensure the cassandra cluster consist in at least 2 nodes
    status = cass_host.check_output("nodetool status")
    upnodes = [row for row in status.splitlines() if row.startswith("UN")]
    assert len(upnodes) >= 2

    # check we do have some archived content in cassandra
    orig_resp = cass_host.check_output("cqlsh -e 'SELECT url FROM swh.origin;'")
    origs = {url.strip() for url in orig_resp.strip().splitlines()[2:-1]}
    missing_origins = {url for _, url in origins} - origs
    assert not missing_origins, origs

    for otype in (
        "origin",
        "origin_visit",
        "origin_visit_status",
        "content",
        "directory",
        "revision",
        "release",
        "snapshot",
    ):
        objs = cass_host.check_output(f"cqlsh -e 'SELECT * FROM swh.{otype};'")
        m = re.match(r"\((?P<rows>\d+) rows\)", objs.splitlines()[-1])
        assert m, objs
        assert int(m.group("rows"))
