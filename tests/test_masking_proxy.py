# Copyright (C) 2024  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

import json
from contextlib import contextmanager

import pytest
import requests

from .utils import compose_host_for_service


@pytest.fixture(scope="module")
def compose_services():
    return [
        "docker-helper",
        "docker-proxy",
        "swh-lister",
        "swh-loader",
        "swh-scheduler-journal-client",
        "swh-scheduler-listener",
        "swh-scheduler-runner",
        "swh-web",
    ]


@pytest.fixture(scope="module")
def storage_public_service(docker_compose):
    return compose_host_for_service(docker_compose, "swh-storage-public")


# swh-py-template.git README.rst
CONTENT_SWHID = "swh:1:cnt:a6d1888d25fd8e84986f386ee0cdc8a1fc3c09b4"


@pytest.fixture
def new_request(storage_public_service):
    @contextmanager
    def _new_request(slug):
        storage_public_service.check_output(
            f"swh storage masking new-request -m 'new {slug}' '{slug}'"
        )
        yield
        storage_public_service.check_output(
            f"swh storage masking clear-request -m 'clear {slug}' '{slug}'"
        )

    return _new_request


@pytest.fixture(scope="module")
def add_masking(storage_public_service):
    def _add_masking(request, swhid, new_state):
        storage_public_service.check_output(
            f"echo '{swhid}' | "
            "swh storage masking update-objects "
            f"-m 'update {request}' "
            f"'{request}' '{new_state}'"
        )

    return _add_masking


def test_visible_content_is_accessible(origins, new_request, add_masking, nginx_url):
    with new_request("test-visible"):
        add_masking("test-visible", CONTENT_SWHID, "visible")
        response = requests.request(
            "GET", f"{nginx_url}/api/1/content/sha1_git:{CONTENT_SWHID.split(':')[-1]}/"
        )
        assert response.status_code == 200, response.text
        response = requests.request(
            "GET",
            f"{nginx_url}/browse/content/sha1_git:{CONTENT_SWHID.split(':')[-1]}/",
        )
        assert response.status_code == 200, response.text


def test_masked_content_is_unavailable(origins, new_request, add_masking, nginx_url):
    with new_request("test-masked"):
        add_masking("test-masked", CONTENT_SWHID, "restricted")
        response = requests.request(
            "GET",
            f"{nginx_url}/api/1/content/sha1_git:{CONTENT_SWHID.split(':')[-1]}/",
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 403, response.text
        d = json.loads(response.text)
        assert CONTENT_SWHID in d["reason"]
        assert d["masked"][CONTENT_SWHID][0]["status"] == "restricted"
        request_id = d["masked"][CONTENT_SWHID][0]["request"]
        response = requests.request(
            "GET",
            f"{nginx_url}/browse/content/sha1_git:{CONTENT_SWHID.split(':')[-1]}/",
            headers={"Accept": "text/html"},
        )
        assert response.status_code == 403, response.text
        assert (
            "Some requested objects are currently under restricted access"
            in response.text
        )
        assert CONTENT_SWHID in response.text
        assert request_id in response.text
