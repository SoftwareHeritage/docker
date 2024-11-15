# Copyright (C) 2019-2024  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

import functools
import json
from typing import List

import pytest

from .conftest import WFI_TIMEOUT, compose_host_for_service
from .utils import retry_until_success

SAMPLE_METADATA = """\
<?xml version="1.0" encoding="utf-8"?>
<entry xmlns="http://www.w3.org/2005/Atom"
       xmlns:swh="https://www.softwareheritage.org/schema/2018/deposit"
       xmlns:codemeta="https://doi.org/10.5063/SCHEMA/CODEMETA-2.0"
       xmlns:schema="http://schema.org/">
  <title>Test Software</title>
  <codemeta:author>
    <codemeta:name>No One</codemeta:name>
  </codemeta:author>
  <swh:deposit>
    <swh:metadata-provenance>
        <schema:url>some-metadata-provenance-url</schema:url>
    </swh:metadata-provenance>
  </swh:deposit>
</entry>
"""


@pytest.fixture(scope="module")
def compose_files() -> List[str]:
    return ["compose.yml", "compose.deposit.yml"]


@pytest.fixture(scope="module")
def compose_services():
    return [
        "docker-helper",
        "docker-proxy",
        "swh-deposit",
        "swh-indexer-journal-client-remd",
        "swh-lister",  # required for the scheduler runner to start
        "swh-loader",
        "swh-loader-deposit",
        "swh-scheduler-journal-client",
        "swh-scheduler-listener",
        "swh-scheduler-runner",
    ]


# scope='module' so we use the same container for all the tests in a given test
# file
@pytest.fixture(scope="module")
def deposit_host(request, docker_compose, scheduler_host):
    # ensure deposit tasks are registered
    task_list = scheduler_host.check_output("swh scheduler task-type list")
    assert "load-deposit:" in task_list
    assert "check-deposit:" in task_list

    deposit_host = compose_host_for_service(docker_compose, "swh-deposit")
    deposit_host.check_output("echo 'print(\"Hello World!\")\n' > /tmp/hello.py")
    deposit_host.check_output("tar -C /tmp -czf /tmp/archive.tgz /tmp/hello.py")
    deposit_host.check_output(f"echo '{SAMPLE_METADATA}' > /tmp/metadata.xml")
    deposit_host.check_output(f"wait-for-it swh-deposit:5006 -t {WFI_TIMEOUT}")
    # return a testinfra connection to the container
    yield deposit_host


def check_deposit_done(deposit_host, deposit_id):
    try:
        status = json.loads(
            deposit_host.check_output(
                "swh deposit status --format json --username test --password test "
                f"--url http://nginx/deposit/1 --deposit-id {deposit_id}"
            )
        )
    except AssertionError:
        return False
    else:
        return status.get("deposit_status") == "done"


def test_admin_collection(deposit_host):
    # 'deposit_host' binds to the container
    assert deposit_host.check_output("swh deposit admin collection list") == "test"


def test_admin_user(deposit_host):
    assert deposit_host.check_output("swh deposit admin user list") == "test"


def test_create_deposit_simple(deposit_host):
    deposit = deposit_host.check_output(
        "swh deposit upload --format json --username test --password test "
        "--url http://nginx/deposit/1 "
        "--archive /tmp/archive.tgz "
        "--name test_deposit --author somebody"
    )
    deposit = json.loads(deposit)
    assert set(deposit.keys()) == {
        "deposit_id",
        "deposit_status",
        "deposit_status_detail",
        "deposit_date",
    }
    # the deposit might be already verified byt the time the update query completed
    assert deposit["deposit_status"] in ("deposited", "verified")
    deposit_id = deposit["deposit_id"]

    retry_until_success(
        functools.partial(check_deposit_done, deposit_host, deposit_id),
        error_message="Deposit loading failed",
        max_attempts=60,
    )


def test_create_deposit_with_metadata(deposit_host):
    deposit = deposit_host.check_output(
        "swh deposit upload --format json --username test --password test "
        "--url http://nginx/deposit/1 "
        "--archive /tmp/archive.tgz "
        "--metadata /tmp/metadata.xml"
    )
    deposit = json.loads(deposit)

    assert set(deposit.keys()) == {
        "deposit_id",
        "deposit_status",
        "deposit_status_detail",
        "deposit_date",
    }
    # the deposit might be already verified byt the time the update query completed
    assert deposit["deposit_status"] in ("deposited", "verified")
    deposit_id = deposit["deposit_id"]

    retry_until_success(
        functools.partial(check_deposit_done, deposit_host, deposit_id),
        error_message="Deposit loading failed",
        max_attempts=60,
    )


def test_create_deposit_multipart(deposit_host):
    deposit = deposit_host.check_output(
        "swh deposit upload --format json --username test --password test "
        "--url http://nginx/deposit/1 "
        "--archive /tmp/archive.tgz "
        "--partial"
    )
    deposit = json.loads(deposit)

    assert set(deposit.keys()) == {
        "deposit_id",
        "deposit_status",
        "deposit_status_detail",
        "deposit_date",
    }
    assert deposit["deposit_status"] == "partial"
    deposit_id = deposit["deposit_id"]

    deposit = deposit_host.check_output(
        "swh deposit upload --format json --username test --password test "
        "--url http://nginx/deposit/1 "
        "--metadata /tmp/metadata.xml "
        "--deposit-id %s" % deposit_id
    )
    deposit = json.loads(deposit)
    # the deposit might be already verified byt the time the update query completed
    assert deposit["deposit_status"] in ("deposited", "verified")
    assert deposit["deposit_id"] == deposit_id

    retry_until_success(
        functools.partial(check_deposit_done, deposit_host, deposit_id),
        error_message="Deposit loading failed",
        max_attempts=60,
    )
