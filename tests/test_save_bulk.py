# Copyright (C) 2024  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

import re
from typing import List

import pytest

from .utils import generate_bearer_token, retry_until_success


@pytest.fixture(scope="module")
def compose_files() -> List[str]:
    return [
        "compose.yml",
        "compose.deposit.yml",
        "compose.keycloak.yml",
    ]


@pytest.fixture(scope="module")
def compose_services() -> List[str]:
    return [
        "docker-helper",
        "docker-proxy",
        "swh-storage",
        "swh-objstorage",
        "swh-scheduler",
        "swh-scheduler-journal-client",
        "swh-scheduler-runner",
        "swh-scheduler-listener",
        "swh-scheduler-schedule-high-priority-first-visits",
        "swh-web",
        "swh-loader",
        "swh-lister",
        "keycloak",
    ]


@pytest.fixture(scope="module")
def origin_urls(origin_urls):
    return origin_urls + [
        (
            "tarball-directory",
            "https://gitlab.softwareheritage.org/swh/devel/swh-counters/-/"
            "archive/v0.11.0/swh-counters-v0.11.0.tar.gz",
        )
    ]


def test_save_bulk(docker_compose, webapp_host, api_get, origin_urls):
    print("Generating a bearer token for granted user")
    bearer_token = retry_until_success(
        lambda: generate_bearer_token(
            webapp_host,
            # user johndoe has the swh.web.api.save_bulk permission set
            # see services/keycloak/keycloak_swh_setup.py script
            username="johndoe",
            password="johndoe-swh",
        )
    )

    print("Submitting origins to load through save bulk Web API endpoint")
    resp = api_get(
        "origin/save/bulk/",
        verb="POST",
        headers={"Authorization": f"Bearer {bearer_token}"},
        json=[
            {"visit_type": visit_type, "origin_url": origin_url}
            for visit_type, origin_url in origin_urls
        ],
    )

    assert resp.get("status") == "accepted"

    request_info_url = resp["request_info_url"]

    def check_save_bulk_lister_execution():
        matcher = re.compile(
            r".*Task swh.lister.save_bulk.tasks.SaveBulkListerTask.*succeeded.*"
        )
        lister_logs = docker_compose.check_compose_output("logs swh-lister")
        return any(
            matcher.match(line)
            for line in lister_logs.splitlines()
            if "INFO/ForkPoolWorker" in line
        )

    print("Checking save bulk lister was successfully executed")
    retry_until_success(check_save_bulk_lister_execution)

    def check_origins_scheduled_and_visited():
        resp = api_get(
            request_info_url,
            headers={"Authorization": f"Bearer {bearer_token}"},
        )
        assert len(resp) == len(origin_urls)
        return all(
            origin_info["last_visit_status"] == "successful" for origin_info in resp
        )

    print("Checking listed origins were scheduled and loaded into the archive")
    retry_until_success(check_origins_scheduled_and_visited)

    for visit_type, origin_url in origin_urls:
        resp = api_get(f"origin/{origin_url}/visit/latest/")
        assert resp["type"] == visit_type
