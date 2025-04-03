# Copyright (C) 2025  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

import re

import pytest

from .utils import retry_until_success

MAVEN_REPOSITORY_BASE_URL = "https://mavenrepo.openmrs.org/releases/"


@pytest.fixture(scope="module")
def compose_services():
    return [
        "docker-helper",
        "docker-proxy",
        "swh-lister",
        "swh-loader",  # required for the scheduler runner to start
        "swh-scheduler-journal-client",
        "swh-scheduler-listener",
        "swh-scheduler-runner",
        "swh-storage",
    ]


def test_maven_lister(scheduler_host, docker_compose):
    task = scheduler_host.check_output(
        "swh scheduler task add -p oneshot list-maven-full "
        f"url={MAVEN_REPOSITORY_BASE_URL} with_github_session=false"
    )
    m = re.search(r"^Task (?P<id>\d+)$", task, flags=re.MULTILINE)
    assert m
    taskid = m.group("id")
    assert int(taskid) > 0

    def check_maven_bulk_lister_execution():
        matcher = re.compile(
            r".*Task swh.lister.maven.tasks.FullMavenLister.*succeeded.*"
            r"{.*, 'origins': (?P<origins>[0-9]+)}"
        )
        lister_logs = docker_compose.check_compose_output("logs swh-lister")
        for line in lister_logs.splitlines():
            if "INFO/ForkPoolWorker" in line:
                m = matcher.match(line)
                if m and int(m.group("origins")) > 0:
                    return True
        return False

    retry_until_success(
        check_maven_bulk_lister_execution, error_message="Maven lister execution failed"
    )
