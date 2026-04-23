# Copyright (C) 2026  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

from urllib.parse import quote_plus

import pytest


@pytest.fixture(scope="module")
def compose_services():
    return [
        "docker-helper",
        "docker-proxy",
        "swh-lister",  # required for the scheduler runner to start
        "swh-loader",
        "swh-scheduler-journal-client",
        "swh-scheduler-listener",
        "swh-scheduler-runner",
        "swh-web",
    ]


@pytest.fixture(scope="module")
def origin_urls():
    return [("svn", "https://subversion.renater.fr/anonscm/svn/panda")]


def test_svn_loader(origins, api_get):
    origin_type, url = origins[0]

    # check svn origin was archived
    assert origin_type == "svn"
    origin = api_get(f"origin/{quote_plus(url)}/get/")
    assert origin["url"] == url
    visit = api_get(f"origin/{quote_plus(url)}/visit/latest/")
    assert visit["status"] == "full"

    # check revisions from the svn origin were archived
    snapshot = api_get(f'snapshot/{visit["snapshot"]}/')
    head_rev = snapshot["branches"]["HEAD"]["target"]
    revisions = api_get(f"revision/{head_rev}/log/")

    assert [
        {
            "rev_id": rev["id"],
            "svn_repo_uuid": rev["extra_headers"][0][1],
            "svn_rev_id": rev["extra_headers"][1][1],
        }
        for rev in revisions
    ] == [
        {
            "rev_id": "64c32fb46a376e055b3d800d4e1ed018371904cd",
            "svn_repo_uuid": "c1b84bfa-9d08-4fc1-adce-de16acc981c0",
            "svn_rev_id": "5",
        },
        {
            "rev_id": "e51f092a15b33b235c588b13c40d756f3db8bed8",
            "svn_repo_uuid": "c1b84bfa-9d08-4fc1-adce-de16acc981c0",
            "svn_rev_id": "4",
        },
        {
            "rev_id": "69018ed64ab0831532235288e2fd5e87c45fcc7b",
            "svn_repo_uuid": "c1b84bfa-9d08-4fc1-adce-de16acc981c0",
            "svn_rev_id": "3",
        },
        {
            "rev_id": "96d5bb8d56ab593309fb233e8ea390c852877114",
            "svn_repo_uuid": "c1b84bfa-9d08-4fc1-adce-de16acc981c0",
            "svn_rev_id": "2",
        },
        {
            "rev_id": "84a097926618c728cb023d992e5de8f8ca0d3331",
            "svn_repo_uuid": "c1b84bfa-9d08-4fc1-adce-de16acc981c0",
            "svn_rev_id": "1",
        },
    ]
