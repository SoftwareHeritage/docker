# Copyright (C) 2024  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

from typing import List

import pytest

from .utils import generate_bearer_token, retry_until_success


@pytest.fixture(scope="module")
def compose_files() -> List[str]:
    return ["compose.yml", "compose.deposit.yml", "compose.keycloak.yml"]


@pytest.fixture(scope="module")
def compose_services() -> List[str]:
    return [
        "docker-helper",
        "docker-proxy",
        "keycloak",
        "swh-web",
    ]


def test_keycloak_authentication(webapp_host, api_get):
    # generate a token for admin user
    bearer_token = retry_until_success(
        lambda: generate_bearer_token(webapp_host, username="admin", password="admin")
    )

    # Web API authentication with valid bearer token should succeed
    api_get(
        "origins/",
        verb="HEAD",
        headers={"Authorization": f"Bearer {bearer_token}"},
        raw=True,
    )

    # Web API authentication with invalid bearer token should fail
    with pytest.raises(AssertionError):
        api_get(
            "origins/",
            verb="HEAD",
            headers={"Authorization": f"Bearer {bearer_token[1:-1]}"},
            raw=True,
        )
