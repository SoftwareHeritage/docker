# Copyright (C) 2025  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

import hashlib
import uuid
from functools import partial
from http import HTTPStatus

import pytest

from .utils import api_get as api_get_func
from .utils import compose_host_for_service


@pytest.fixture(scope="module")
def origin_url(origins):
    _, origin_url = origins[0]
    return origin_url


@pytest.fixture
def mention_payload(origin_url, nginx_url):
    return {
        "@context": [
            "https://www.w3.org/ns/activitystreams",
            "https://coar-notify.net",
        ],
        "id": f"urn:uuid:{uuid.uuid4()}",
        "type": ["Announce", "coar-notify:RelationshipAction"],
        "origin": {
            "id": "https://research-organisation.org/repository",
            "inbox": "http://inbox.partner.local",
            "type": "Service",
        },
        "target": {
            "id": "https://another-research-organisation.org/repository",
            "inbox": f"{nginx_url}/coarnotify/",
            "type": "Service",
        },
        "actor": {
            "id": "https://research-organisation.org",
            "name": "Research Organisation",
            "type": "Organization",
        },
        "object": {
            "as:object": origin_url,
            "as:relationship": "https://w3id.org/codemeta/3.0#citation",
            "as:subject": "https://example.com/paper/123/",
            "id": f"urn:uuid:{uuid.uuid4()}",
            "type": "Relationship",
        },
        "context": {
            "id": "https://example.com/paper/123/",
            "type": ["Page", "sorg:AboutPage"],
        },
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
        "swh-scheduler",
        "swh-scheduler-listener",
        "swh-indexer-journal-client-oemd",
        "swh-lister",  # required for the scheduler runner to start
        "swh-loader",
        "swh-idx-storage",
        "swh-web",
    ]


@pytest.fixture(scope="module")
def storage_public_service(docker_compose):
    return compose_host_for_service(docker_compose, "swh-storage-public")


@pytest.fixture(scope="module")
def cn_call(nginx_url, http_session):
    """Make an call to swh-coarnotify."""
    return partial(
        api_get_func,
        nginx_url,
        session=http_session,
    )


@pytest.fixture(scope="module")
def auth_cn_call(cn_call):
    """Make an authenticated call to swh-coarnotify."""
    return partial(
        cn_call,
        headers={"Authorization": "Token 12345", "Content-type": "application/ld+json"},
    )


def test_head_includes_inbox_link(docker_compose, cn_call, nginx_url):
    response = cn_call(
        "coarnotify/",
        verb="HEAD",
        raw=True,
        status_code=HTTPStatus.OK,
    )
    assert nginx_url in response.headers["Link"]


def test_mention(
    storage_public_service,
    auth_cn_call,
    nginx_url,
    origin_url,
    mention_payload,
    api_poll,
    api_get,
):
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

    swhid = f"swh:1:ori:{hashlib.sha1(str.encode(origin_url)).hexdigest()}"

    raw_extrinsic_metadata = api_get(
        f"raw-extrinsic-metadata/swhid/{swhid}/",
        params={
            "authority": f"registry {mention_payload['origin']['id']}",
        },
    )

    assert len(raw_extrinsic_metadata) == 1
    assert raw_extrinsic_metadata[0]["format"] == "coarnotify-mention-v1"

    extrinsic_metadata = api_get_func(
        nginx_url,
        "api/1/extrinsic-metadata/origin/",
        params={"origin_url": origin_url},
    )

    assert len(extrinsic_metadata) == 1

    assert (
        extrinsic_metadata[0]["citation"]["schema:ScholarlyArticle"]["id"]
        == mention_payload["object"]["as:subject"]
    )
