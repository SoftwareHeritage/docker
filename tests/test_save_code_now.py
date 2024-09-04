# Copyright (C) 2023-2024  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information


import pytest

from .utils import retry_until_success

# small git repository that takes a couple of seconds to load into the archive
ORIGIN_URL = "https://github.com/anlambert/highlightjs-line-numbers.js"
VISIT_TYPE = "git"


@pytest.fixture(
    scope="module",
    params=[
        ["compose.yml"],
        [
            "compose.yml",
            "compose.webhooks.yml",
        ],
    ],
    ids=["pull request status", "push request status"],
)
def compose_files(request):
    return request.param


@pytest.fixture(scope="module")
def compose_services(compose_files):
    common_services = [
        "docker-helper",
        "docker-proxy",
        "swh-lister",  # required for the scheduler runner to start
        "swh-loader",
        "swh-scheduler-journal-client",
        "swh-scheduler-listener",
        "swh-scheduler-runner-priority",
        "swh-web",
    ]
    if "compose.webhooks.yml" in compose_files:
        return common_services + ["swh-webhooks-journal-client"]
    else:
        return common_services + ["swh-web-cron"]


def test_save_code_now(webapp_host, api_get):
    api_path = f"origin/save/{VISIT_TYPE}/url/{ORIGIN_URL}/"
    # create save request
    api_get(api_path, verb="POST")
    # wait until it was successfully processed
    retry_until_success(
        lambda: api_get(api_path)[0].get("save_task_status") == "succeeded",
        error_message="Save Code Now request did not succeed",
        max_attempts=60,
    )
