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
from .utils import retry_until_success


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
    ]


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


@pytest.fixture(scope="module")
def storage_rpc_url(nginx_url):
    return f"{nginx_url}/rpc/storage/"


@pytest.fixture(scope="module")
def indexer_storage_rpc_url(nginx_url):
    return f"{nginx_url}/rpc/indexer-storage/"


def test_head_includes_inbox_link(docker_compose, cn_call, nginx_url):
    response = cn_call(
        "coarnotify/",
        verb="HEAD",
        raw=True,
        status_code=HTTPStatus.OK,
    )
    assert nginx_url in response.headers["Link"]


def test_mention(
    docker_compose,
    auth_cn_call,
    nginx_url,
    origin_url,
    storage_rpc_url,
    indexer_storage_rpc_url,
    mention_payload,
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

    def get_raw_extrinsic_metadata():
        raw_extrinsic_metadata = api_get(  # needs a retry
            f"raw-extrinsic-metadata/swhid/{swhid}/",
        )
        print(raw_extrinsic_metadata)
        return raw_extrinsic_metadata

    raw_extrinsic_metadata = retry_until_success(
        get_raw_extrinsic_metadata,
        error_message=f"Unable to fetch raw extrinsic metadata of {origin_url} {swhid}",
    )

    assert len(raw_extrinsic_metadata) == 1

    extrinsic_metadata = api_get_func(
        nginx_url,
        f"api/1/extrinsic-metadata/origin/{swhid}",
        params={"origin_url": origin_url},
    )
    print(extrinsic_metadata)

    assert (
        extrinsic_metadata["citation"]["schema:ScholarlyArticle"]["id"]
        == mention_payload["object"]["as:subject"]
    )
