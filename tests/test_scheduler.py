# Copyright (C) 2025  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

import re
import time

import pytest

from .utils import filter_origins, retry_until_success


@pytest.fixture(scope="module")
def compose_services():
    return [
        "docker-helper",
        "docker-proxy",
        "swh-loader",
        "swh-lister",  # required for the scheduler runner to start
        "swh-loader",
        "swh-scheduler-journal-client",
        "swh-scheduler-listener",
        "swh-scheduler-runner",
    ]


def test_origins_to_load_scheduling(docker_compose, scheduler_host, origin_urls):
    origin_urls = [(otype, filter_origins(urls)) for (otype, urls) in origin_urls]
    task_ids = {}

    for origin_type, origin_url in origin_urls:
        print(f"Scheduling {origin_type} loading task for {origin_url}")
        task = scheduler_host.check_output(
            f"swh scheduler task add load-{origin_type} url={origin_url}"
        )
        m = re.search(r"^Task (?P<id>\d+)$", task, flags=re.MULTILINE)
        assert m
        taskid = m.group("id")
        assert int(taskid) > 0
        task_ids[origin_url] = taskid

    # ids of the tasks still running
    ids = list(task_ids.values())
    t0 = time.time()

    def check_origins_load_statuses():
        taskid = ids.pop(0)
        origin_url = next(k for k, v in task_ids.items() if v == taskid)
        status = scheduler_host.check_output(
            f"swh scheduler task list --list-runs --task-id {taskid}"
        )
        if "Executions:" in status:
            if "[eventful]" in status:
                print(f"Loading of {origin_url} is done (took {time.time() - t0:.2f}s)")
            elif "[started]" in status or "[scheduled]" in status:
                ids.append(taskid)
            elif "[failed]" in status:
                loader_logs = docker_compose.check_compose_output("logs swh-loader")
                raise AssertionError(
                    "Loading execution failed\n"
                    f"status: {status}\n"
                    f"loader logs: " + loader_logs
                )
            else:
                raise AssertionError(
                    f"Loading execution failed, task status is {status}"
                )
        else:
            ids.append(taskid)

        return not ids

    retry_until_success(check_origins_load_statuses)
