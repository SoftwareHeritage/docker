# Copyright (C) 2025  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

from typing import Iterator, List, Tuple

import grpc
import pytest
import swh.graph.grpc.swhgraph_pb2 as swhgraph
import swh.graph.grpc.swhgraph_pb2_grpc as swhgraph_grpc

from .conftest import service_url
# fmt: off
# to test vault cooking with graph use
from .test_vault import test_vault_git_bare  # noqa
from .utils import (compose_host_for_service, generate_bearer_token,
                    retry_until_success)

# fmt: on


@pytest.fixture(scope="module")
def compose_files() -> List[str]:
    return [
        "compose.yml",
        "compose.graph.yml",
        "compose.keycloak.yml",
        "compose.vault.yml",
    ]


@pytest.fixture(scope="module")
def compose_services() -> List[str]:
    return [
        "docker-helper",
        "docker-proxy",
        "swh-lister",  # required for the scheduler runner to start
        "swh-loader",
        "swh-scheduler-journal-client",
        "swh-scheduler-listener",
        "swh-scheduler-runner",
        "swh-graph",
        "swh-web",
        "swh-counters-journal-client",
        "swh-vault",
        "swh-vault-worker",
    ]


@pytest.fixture(scope="module")
def graph_service(docker_compose) -> Iterator[str]:
    # run a container in which test commands are executed
    graph_host = compose_host_for_service(docker_compose, "swh-graph")
    assert graph_host
    yield graph_host


@pytest.fixture(scope="module")
def graph_grpc_url(docker_compose, docker_network_gateway_ip) -> str:
    return service_url(
        docker_compose, "swh-graph", docker_network_gateway_ip, port=50091
    ).replace("http://", "")


@pytest.fixture(scope="module")
def graph_rpc_url(nginx_url) -> str:
    return f"{nginx_url}/rpc/graph"


def test_graph_rpc_server(http_session, graph_rpc_url, origins):
    def check_graph_rpc_server():
        response = http_session.get(f"{graph_rpc_url}/stats")
        if response.status_code != 200:
            return False
        else:
            graph_stats = response.json()
            return graph_stats["num_nodes"] > 0 and graph_stats["num_edges"] > 0

    retry_until_success(
        check_graph_rpc_server, error_message="Failed to query graph RPC server"
    )


def test_graph_grpc_server(graph_grpc_url, origins):
    def check_graph_grpc_server():
        with grpc.insecure_channel(graph_grpc_url) as channel:
            stub = swhgraph_grpc.TraversalServiceStub(channel)
            try:
                response = stub.Stats(swhgraph.StatsRequest())
            except Exception:
                return False
            else:
                return response.num_nodes > 0 and response.num_edges > 0

    retry_until_success(
        check_graph_grpc_server, error_message="Failed to query graph GRPC server"
    )


def test_graph_find_context(graph_service, origins):
    def check_graph_find_context():
        try:
            output = graph_service.check_output(
                "swh graph find-context -c "
                "swh:1:cnt:524175c2bad0b35b975f79284c2f5a6d5eaf2eb4"
            )
        except Exception:
            return False
        else:
            return (
                "https://gitlab.softwareheritage.org/swh/devel/swh-py-template.git"
                in output
            )

    retry_until_success(
        check_graph_find_context, error_message="Failed to query graph GRPC server"
    )


def test_graph_masked_node(
    graph_service, graph_grpc_url, storage_public_service, origins
):
    masked_swhids = [
        "swh:1:cnt:44de9330c2954144ccf8a8f32ac83f2364314e2e",
        "swh:1:cnt:16a616899a3d83907db8e4a8c8a8c9c58ee3a95b",
    ]

    def check_graph_masked_node():
        with grpc.insecure_channel(graph_grpc_url) as channel:
            stub = swhgraph_grpc.TraversalServiceStub(channel)
            try:
                stub.GetNode(swhgraph.GetNodeRequest(swhid=masked_swhids[0]))
            except Exception as e:
                return f"Unavailable node: {masked_swhids[0]}" in str(e)
            else:
                return False

    graph_service.check_output("wait-for-it swh-graph:50091 -s --timeout=0")

    storage_public_service.check_output(
        "swh storage masking new-request -m 'test' test"
    )
    for masked_swhid in masked_swhids:
        storage_public_service.check_output(
            f"echo '{masked_swhid}' | "
            "swh storage masking update-objects -m 'test' -f - test restricted"
        )

    retry_until_success(
        check_graph_masked_node, error_message="Failed to query graph GRPC server"
    )


def test_graph_web_api(graph_service, api_get, origins):
    graph_service.check_output("wait-for-it swh-graph:50091 -s --timeout=0")

    # generate a token for admin user
    bearer_token = retry_until_success(
        lambda: generate_bearer_token(
            graph_service,
            # user johndoe has the swh.web.api.graph permission set
            # see services/keycloak/keycloak_swh_setup.py script
            username="johndoe",
            password="johndoe-swh",
        )
    )

    # Web API authentication with valid bearer token should succeed
    stats = api_get(
        "graph/stats/",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )

    assert stats["num_nodes"] > 0 and stats["num_edges"] > 0


@pytest.fixture(scope="module")
def origin_urls(tiny_git_repo) -> List[Tuple[str, str]]:
    return [("git", tiny_git_repo), ("git", "https://github.com/rdicosmo/parmap.git")]


def swh_datasets_version():
    import subprocess

    return subprocess.check_output(
        [
            "docker",
            "run",
            "--entrypoint",
            "",
            "swh/stack",
            "/bin/bash",
            "-c",
            "cat pip-installed.txt | grep swh.datasets | awk '{print $2}'",
        ]
    ).decode()[:-1]


@pytest.mark.skipif(
    swh_datasets_version() == "2.0.3",
    reason="swh-datasets v2.0.3 is not compatible with swh-graph v9.0",
)
def test_compression_pipeline(graph_service, origins):
    graph_service.check_output(
        "swh datasets luigi "
        "--base-directory /srv/softwareheritage/datasets "
        "--base-sensitive-directory /srv/softwareheritage/datasets-sensitive "
        "--dataset-name test "
        "CompressGraph "
        "-- "
        "--local-scheduler "
        "--LocalExport-export-task-type ExportGraph "
        "--ExportGraph-config-file config.yml "
        "--check-flavor none"
    )
