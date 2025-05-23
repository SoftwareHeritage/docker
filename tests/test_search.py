# Copyright (C) 2023-2024  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

import re
from typing import List
from urllib.parse import quote_plus

import pytest

from .utils import retry_until_success


@pytest.fixture(scope="module")
def compose_files() -> List[str]:
    return ["compose.yml", "compose.search.yml"]


@pytest.fixture(scope="module")
def compose_services():
    return [
        "docker-helper",
        "docker-proxy",
        "swh-indexer-journal-client-oimd",
        "swh-lister",  # required for the scheduler runner to start
        "swh-loader",
        "swh-scheduler-journal-client",
        "swh-scheduler-listener",
        "swh-scheduler-runner",
        "swh-search",
        "swh-search-journal-client-objects",
        "swh-search-journal-client-indexed",
        "swh-web",
    ]


@pytest.fixture(scope="module")
def origin_urls(small_git_repo, tiny_git_repo):
    # When changing this, beware of the 'metadata_patterns' below that probably
    # needs updating...
    return [
        ("git", small_git_repo),
        ("git", tiny_git_repo),
        ("git", "https://github.com/rdicosmo/parmap.git"),
        ("pypi", "https://pypi.org/project/swh.counters/"),
        ("pypi", "https://pypi.org/project/swh.search/"),
    ]


# Here is a quick explanation of what's going on in this origin MD scaffolding:
# first we load a bunch of origins; the pypi ones do have intrinsic metadata
# (the python packaging stuff), and Roberto's parmap comes with a codemeta file
# in the source tree. The 2 swh-xxx git repos do not trigger a IMD detection
# (for now, files like pyproject.toml etc are not detected as IMD).
#
# The loading of these origins generates a bunch of messages in kafka, in
# particular 'origin_visit_status' messages. The 'swh-indexer-worker-journal'
# service is a journal client consuming this topic (it is running as
#
#   swh indexer journal-client origin_intrinsic_metadata
#
# so it's executing only the intrinsic metadata indexer which consumes only the
# origin_visit_status topic). This journal client will look for known intrinsic
# metadata files in the root directory of each head of listed origins.
# Detected MD files are loaded and translated into a common data model then
# stored in the metadata indexer storage (swh-idx-storage) as both (?) and
# directory_intrinsic_metadata and origin_intrinsic_metadata.
#
# The indexer storage, while adding rows to its DB, also produces kafka
# messages for indexed objects under the swh.journal.indexed prefix (as
# 'directory_intrinsic_metadata' and 'origin_intrinsic_metadata' topics).
#
# The 'swh-search-journal-client-objects' service is a journal client consuming
# the swh.journal.objects.{origin,origin_visit_status} topics. Then:
# - the 'origin' topic is used to fill the search db (elasticsearch) with
#   origin URLs only.
# - the 'origin_visit_status' topic is also used to fill the search db with
#   origin URLs with additional fields (has_visit, nb_visits, last visit, last
#   snapshot, etc.)
#
# The 'swh-search-journal-client-indexed' service is a journal client consuming
# the swh.journal.indexed.origin_intrinsic_metadata topic. Then:
# - the 'origin_intrinsic_metadata' is used to fill the (es) search db with
#   origin MD linked to the url (as jsonld)
#
# When searching for IMD via the public API endpoint 'origin/metadata_search',
# the web frontend will:
# - perform a origin_search(metadata_pattern='<fulltext>') on swh-search
# - if it did not return anything, it queries the indexer storage using the
#   'origin_intrinsic_metadata_search_fulltext()' method
# - the gathered origin URLs with their metadata are then returned


def test_origin_metadata_search(origins, docker_compose, nginx_get, api_get):
    # preliminary checks:
    for _, url in origins:
        # 1. Check the origin is in the archive (just in case)
        origin = api_get(f"origin/{quote_plus(url)}/get")
        assert origin["url"] == url
        # 2. Check the visit was indeed eventful
        visit = api_get(f"origin/{quote_plus(url)}/visit/latest")
        assert visit["status"] == "full"

    # 3. Check origins are in elasticsearch (as a result of the
    # swh-search-journal-client-objects consuming the
    # swh.journal.objects.origin topic at least)
    es_resp = nginx_get("es/origin/_search")
    es_origins = [
        (hit["_source"]["visit_types"][0], hit["_source"]["url"])
        for hit in es_resp["hits"]["hits"]
    ]
    assert set(es_origins) == set(origins)

    metadata_patterns = {
        "https://pypi.org/project/swh.counters/": "Software Heritage archive counters",
        "https://pypi.org/project/swh.search/": "Software Heritage search service",
        "https://github.com/rdicosmo/parmap.git": "roberto",
    }
    imd_urls = set(metadata_patterns)

    # 4. Wait for the swh-search journal client to have processed the intrinsic MD.
    # For this, we just scrape the logs of the
    # swh-search-journal-client-indexed service to look for log entries showing
    # the origins have been indexed. The service NEEDS to be executed with
    # DEBUG log level.
    def check_intrinsic_metadata_processed():
        matcher = re.compile(r"'id': '(?P<url>[^']+)'")

        logs = docker_compose.check_compose_output(
            "logs swh-search-journal-client-indexed"
        )
        omd_proc_raws = [
            raw
            for raw in logs.splitlines()
            if "DEBUG:root:processing origin intrinsic_metadata" in raw
        ]
        urls = [
            m.group("url") for m in (matcher.search(row) for row in omd_proc_raws) if m
        ]
        return set(urls) == imd_urls

    retry_until_success(
        check_intrinsic_metadata_processed,
        error_message=(
            "swh-search journal client did not process "
            "intrinsic metadata in a timely manner"
        ),
    )

    # 5. query swh-search directly with metadata_pattern=fulltext to check
    # these iMD have been indexed in ES.
    for url, pattern in metadata_patterns.items():

        def check_metadata_search_result():
            mds = nginx_get(
                "rpc/search/origin/search",
                verb="POST",
                json={"metadata_pattern": pattern},
            )
            return {x["url"] for x in mds["d"]["results"]} == {url}

        retry_until_success(
            check_metadata_search_result,
            error_message=(
                "swh-indexer-worker-journal(?) did not process origins with "
                "intrinsic metadata in a timely manner"
            ),
            max_attempts=30,
        )

    # 6. Check the metadata indexer storage (!) have them indexed. Unfortunately
    # we do not have an easy way to figure if the indexer-worker-journal-client
    # service did process said origins (not enough logging), so just poll the
    # service instead for now...
    def check_metadata_in_indexer_storage():
        imd = nginx_get(
            "rpc/indexer-storage/origin_intrinsic_metadata",
            verb="POST",
            json={"urls": [url for _, url in origins]},
        )
        return {x["d"]["id"] for x in imd} == imd_urls

    retry_until_success(
        check_metadata_in_indexer_storage,
        error_message=(
            "swh-indexer-worker-journal did not process origins with "
            "intrinsic metadata in a timely manner"
        ),
    )

    # Check the metadata can be queried via the public API
    # Note that this actually does 2 things: ask ES for origins matching the
    # fulltext, then query the indexer-storage for each selected origin to
    # retrieve the actually stored intrinsic metadata.
    mds = api_get("origin/metadata-search", params={"limit": 10, "fulltext": "roberto"})
    assert len(mds) == 1
    md = mds[0]
    assert md["metadata"]["mappings"] == ["codemeta"]
    assert md["metadata"]["metadata"]["name"] == "Parmap"
    assert md["metadata"]["metadata"]["programmingLanguage"] == "OCaml"
    assert md["metadata"]["tool"]["name"] == "swh-metadata-detector"
    imd = api_get(f"origin/{quote_plus(md['url'])}/intrinsic-metadata")
    assert md["metadata"]["metadata"] == imd

    mds = api_get(
        "origin/metadata-search",
        params={"limit": 10, "fulltext": "Software Heritage search service"},
    )
    assert len(mds) == 1
    md = mds[0]
    assert md["metadata"]["mappings"] == ["npm", "pkg-info"]
    assert md["metadata"]["metadata"]["name"] == [
        "swh-search-query-language-parser",
        "swh.search",
    ]
    assert md["metadata"]["metadata"]["description"] == [
        "Parser for Software Heritage archive search query language",
        "Software Heritage search service",
    ]
    assert md["metadata"]["tool"]["name"] == "swh-metadata-detector"
    imd = api_get(f"origin/{quote_plus(md['url'])}/intrinsic-metadata")
    assert md["metadata"]["metadata"] == imd

    # Check a more generic query return both pypi packages
    mds = api_get(
        "origin/metadata-search", params={"limit": 10, "fulltext": "Software Heritage"}
    )
    assert len(mds) == 2
