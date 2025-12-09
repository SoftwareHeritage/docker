# Copyright (C) 2025  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information


import pytest

MAVEN_REPOSITORY_BASE_URL = "https://mavenrepo.openmrs.org/releases/"


@pytest.fixture(scope="module")
def compose_services():
    return [
        "docker-helper",
        "docker-proxy",
        "swh-lister",
        "swh-storage",
        "swh-scheduler",
    ]


def test_maven_lister(lister_host):
    lister_host.check_output(
        (
            f"swh lister run -l maven url={MAVEN_REPOSITORY_BASE_URL} "
            "with_github_session=false"
        )
    )
