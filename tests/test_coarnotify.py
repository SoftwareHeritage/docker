# Copyright (C) 2025  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

from functools import partial
from http import HTTPStatus

import pytest

from .utils import api_get as api_get_func

mention_payload = {
    "@context": ["https://www.w3.org/ns/activitystreams", "https://coar-notify.net"],
    "actor": {
        "id": "https://research-organisation.org",
        "name": "Research Organisation",
        "type": "Organization",
    },
    "context": {
        "id": "https://another-research-organisation.org/repository/datasets/item/201203421/",  # noqa: E501
        "ietf:cite-as": "https://doi.org/10.5555/999555666",
        "ietf:item": {
            "id": "https://another-research-organisation.org/repository/datasets/item/201203421/data_archive.zip",  # noqa: E501
            "mediaType": "application/zip",
            "type": ["Object", "sorg:Dataset"],
        },
        "type": ["Page", "sorg:SoftwareSourceCode"],
    },
    "id": "urn:uuid:6908e2d0-ab41-4fbf-8b27-e6d6cf1f7b95",
    "object": {
        "as:object": "https://another-research-organisation.org/repository/datasets/item/201203421/",  # noqa: E501
        "as:relationship": "http://purl.org/vocab/frbr/core#supplement",
        "as:subject": "https://research-organisation.org/repository/item/201203/421/",
        "id": "urn:uuid:74FFB356-0632-44D9-B176-888DA85758DC",
        "type": "Relationship",
    },
    "origin": {
        "id": "https://research-organisation.org/repository",
        "inbox": "http://inbox.partner.local",
        "type": "Service",
    },
    "target": {
        "id": "https://another-research-organisation.org/repository",
        "inbox": "http://localhost:30080/coarnotify/",
        "type": "Service",
    },
    "type": ["Announce", "coar-notify:RelationshipAction"],
}


@pytest.fixture(scope="module")
def compose_files() -> list[str]:
    return ["compose.yml", "compose.coarnotify.yml"]


@pytest.fixture(scope="module")
def compose_services() -> list[str]:
    return [
        "docker-helper",
        "docker-proxy",
        "swh-storage",
        "swh-objstorage",
        "swh-coarnotify",
    ]


@pytest.fixture(scope="module")
def cn_call(nginx_url, http_session):
    """Make an call to swh-coanotify."""
    return partial(
        api_get_func,
        nginx_url,
        session=http_session,
    )


@pytest.fixture(scope="module")
def auth_cn_call(cn_call):
    """Make an authenticated call to swh-coanotify."""
    return partial(
        cn_call,
        headers={"Authorization": "Token 12345"},
    )


def test_head_includes_inbox_link(docker_compose, cn_call, nginx_url):
    response = cn_call(
        "coarnotify/",
        verb="HEAD",
        raw=True,
        status_code=HTTPStatus.OK,
    )
    assert nginx_url in response.headers["Link"]


def test_mention_receipt(docker_compose, auth_cn_call, nginx_url):
    receipt = auth_cn_call(
        "coarnotify/",
        verb="POST",
        json=mention_payload,
        raw=True,
        status_code=HTTPStatus.CREATED,
    )
    location = receipt.headers["location"]
    assert location.startswith(nginx_url)
    path = location.replace(nginx_url + "/", "")
    data = auth_cn_call(
        path,
        verb="GET",
        status_code=HTTPStatus.OK,
    )
    assert data == mention_payload
