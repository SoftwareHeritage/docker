# Copyright (C) 2023-2025  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information


import pytest

from .utils import retry_until_success

# small git repository that takes a couple of seconds to load into the archive
ORIGIN_URL = (
    "https://gitlab.com/gitlab-com/solution-architecture-blueprints/account-plan.git"
)
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
    request_id = api_get(api_path, verb="POST")["id"]

    # wait until it was successfully processed
    def get_request_status(request_id):
        # we want to check if request status is updated either by a cron or
        # a webhook so we get it from webapp database as using the Web API
        # to get request info automatically updates its status
        return webapp_host.check_output(
            "psql -qt service=swh-web -c "
            f"'select loading_task_status from save_origin_request where id = {request_id}'"  # noqa
        ).strip()

    retry_until_success(
        lambda: get_request_status(request_id) == "succeeded",
        error_message="Save Code Now request did not succeed",
        max_attempts=60,
    )
