# Copyright (C) 2023-2024  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

import re
from functools import partial
from time import sleep
from typing import List
from urllib.parse import quote_plus
from uuid import uuid4 as uuid

import pytest
import requests

from .test_vault import test_vault_directory, test_vault_git_bare  # noqa
from .utils import RemovalOperation
from .utils import api_get as api_get_func
from .utils import api_get_directory as api_get_directory_func
from .utils import compose_host_for_service, retry_until_success


@pytest.fixture(scope="module")
def compose_files() -> List[str]:
    return ["compose.yml", "compose.mirror.yml"]


@pytest.fixture(scope="module")
def nginx_mirror_url(docker_compose, compose_cmd, docker_network_gateway_ip) -> str:
    port_output = docker_compose.check_output(f"{compose_cmd} port nginx-mirror 80")
    bound_port = port_output.split(":")[1]
    # as tests could be executed inside a container, we use the docker bridge
    # network gateway ip instead of localhost domain name
    return f"http://{docker_network_gateway_ip}:{bound_port}"


@pytest.fixture(scope="module")
def mirror_api_url(nginx_mirror_url) -> str:
    return f"{nginx_mirror_url}/api/1/"


@pytest.fixture(scope="module")
def api_url(mirror_api_url):
    # this will make all 3 fixtures api_get, api_poll and api_get_directory
    # query the mirror instead of the main archive
    return mirror_api_url


@pytest.fixture(scope="module")
def base_api_url(nginx_url) -> str:
    return f"{nginx_url}/api/1/"


@pytest.fixture(scope="module")
def base_api_get(base_api_url, http_session):
    return partial(api_get_func, base_api_url, session=http_session)


@pytest.fixture(scope="module")
def mirror_api_get(mirror_api_url, http_session):
    return partial(api_get_func, mirror_api_url, session=http_session)


@pytest.fixture(scope="module")
def base_api_get_directory(base_api_url, http_session):
    return partial(api_get_directory_func, base_api_url, session=http_session)


@pytest.fixture(scope="module")
def mirror_api_get_directory(mirror_api_url, http_session):
    return partial(api_get_directory_func, mirror_api_url, session=http_session)


@pytest.fixture(scope="module")
def mirror_public_storage(docker_compose):
    return compose_host_for_service(docker_compose, "swh-mirror-storage-public")


@pytest.fixture()
def mirror_alter_host(docker_compose, mirror_public_storage, bundle_path):
    host = compose_host_for_service(docker_compose, "swh-mirror-notification-watcher")
    print(f"Restore {bundle_path} on the mirror storage")
    print(
        host.check_output(
            "bash -c '"
            f"[[ -a {bundle_path} ]] && "
            f"echo y | swh alter recovery-bundle restore {bundle_path} "
            "--identity /srv/softwareheritage/age-identities.txt || true"
            "'"
        )
    )
    try:
        yield host
    finally:
        # clear masking requests
        print("Clear masking requests")
        requests = mirror_public_storage.check_output(
            "swh storage masking list-requests"
        )
        for slug in re.findall("^📄 (.*)$", requests, re.MULTILINE):
            mirror_public_storage.check_output(
                f"swh storage masking clear-request -m 'for tests' {slug}"
            )


@pytest.fixture()
def removal_identifier():
    return str(uuid())


@pytest.fixture()
def bundle_path(removal_identifier):
    return f"/tmp/removal-{removal_identifier}.swh-recovery-bundle"


@pytest.fixture(scope="module")
def origin_urls(tiny_git_repo, small_git_repo):
    return [
        ("git", tiny_git_repo),
        ("git", small_git_repo),
        (
            "hg",
            [
                "https://hg.sdfa3.org/pygpibtoolkit",
                "https://hg.sr.ht/~douardda/pygpibtoolkit",
            ],
        ),
    ]


def git_repo_removed_from_archive(
    tiny_git_repo, alter_host, origins, removal_identifier, bundle_path
):
    removal_op = RemovalOperation(
        identifier=removal_identifier,
        bundle_path=bundle_path,
        origins=[tiny_git_repo],
    )
    removal_op.run_in(alter_host)
    assert len(removal_op.removed_swhids) > 0
    return removal_op


@pytest.fixture()
def initial_removed(
    alter_host, origins, tiny_git_repo, removal_identifier, bundle_path
):
    yield git_repo_removed_from_archive(
        tiny_git_repo, alter_host, origins, removal_identifier, bundle_path
    )
    print(f"Restore {bundle_path} on the main storage")
    print(
        alter_host.check_output(
            "bash -c '"
            f"[[ -a {bundle_path} ]] "
            f"&& echo restoring bundle: {bundle_path} "
            f"&& echo y | swh alter recovery-bundle restore {bundle_path} "
            "    --identity /srv/softwareheritage/age-identities.txt "
            f"&& rm {bundle_path} "
            # "|| true"
            "'"
        )
    )


@pytest.fixture(scope="module")
def origins(docker_compose, origins, base_api_get, api_get, kafka_api_url):
    # this fixture ensures the origins have been loaded in the primary
    # storage, the mirror is up, and the replayers are done
    check_output = docker_compose.check_compose_output
    while check_output("ps --quiet --status created"):
        sleep(0.2)
    print("Checking there is no dead service")
    assert not check_output("ps --quiet --status dead")
    assert not check_output("ps --quiet --status exited")

    print("Checking core services are reported as ok")
    print("Storage...", end=" ", flush=True)
    assert check_output("ps --quiet --status running swh-storage")
    print("OK")
    print("Mirror Storage...", end=" ", flush=True)
    assert check_output("ps --quiet --status running swh-mirror-storage")
    print("OK")
    print("Kafka REST proxy...", end=" ", flush=True)
    assert check_output("ps --quiet --status running kafka")
    print("OK")

    # check the mirror storage has the proper flavor
    db_desc = check_output("exec -t swh-mirror-storage swh db version storage")
    db_d = {
        k: v
        for k, v in (
            row.strip().split(": ") for row in db_desc.splitlines() if row.strip()
        )
    }
    assert db_d["module"] == "storage:postgresql"
    assert db_d["flavor"] == "mirror"

    expected_urls = set(url for _, url in origins)

    print("Checking origins exists in the main storage")
    # ensure all the origins have been loaded, should not be needed but...
    m_origins = set(x["url"] for x in base_api_get("origins/"))
    assert m_origins == expected_urls, "not all origins have been loaded"

    cluster = requests.get(kafka_api_url).json()["data"][0]["cluster_id"]

    def kget(path):
        url = f"{kafka_api_url}/{cluster}/{path}"
        resp = requests.get(url)
        if resp.status_code == 200:
            return resp.json()
        resp.raise_for_status()

    def check_replayer_done(consumer_group):
        lag_sum = kget(f"consumer-groups/{consumer_group}/lag-summary")
        return lag_sum["total_lag"] == 0

    # wait until the replayer is done
    print("Waiting for the graph replayer to be done")
    retry_until_success(
        partial(check_replayer_done, "swh.storage.mirror.replayer"),
        error_message="Could not detect a condition where the replayer did its job",
        max_attempts=30,
    )

    print("Checking we have origins in the mirror")
    # at this point, origins should be in the mirror storage...
    retry_until_success(
        lambda: {x["url"] for x in api_get("origins/")} == expected_urls,
        error_message="not all origins have been replicated",
        max_attempts=30,
    )

    print("Waiting for the content replayer to be done")
    # wait until the content replayer is done
    retry_until_success(
        partial(check_replayer_done, "swh.objstorage.mirror.replayer"),
        error_message=(
            "Could not detect a condition where the content replayer did its job"
        ),
        max_attempts=30,
    )

    return origins


def test_mirror_replication(
    origins,
    base_api_get,
    base_api_get_directory,
    api_get,
    api_get_directory,
    docker_network_gateway_ip,
):
    # double check we do not query the same endpoint as the main archive one
    assert api_get.args != base_api_get.args
    assert api_get_directory.args != base_api_get_directory.args

    def filter_obj(objd):
        if isinstance(objd, dict):
            return {
                k: filter_obj(v)
                for (k, v) in objd.items()
                if not (
                    isinstance(v, str)
                    and v.startswith(f"http://{docker_network_gateway_ip}:")
                )
            }
        elif isinstance(objd, list):
            return [filter_obj(e) for e in objd]
        else:
            return objd

    print("Check every git object has been replicated in the mirror")
    # check all the objects are present in the mirror...
    for _, origin_url in origins:
        print(f"... for {origin_url}")
        visit1 = base_api_get(f"origin/{quote_plus(origin_url)}/visit/latest/")
        visit2 = api_get(f"origin/{quote_plus(origin_url)}/visit/latest/")
        assert filter_obj(visit1) == filter_obj(visit2)

        snapshot1 = base_api_get(f'snapshot/{visit1["snapshot"]}/')
        snapshot2 = api_get(f'snapshot/{visit2["snapshot"]}/')
        assert filter_obj(snapshot1) == filter_obj(snapshot2)

        assert snapshot1["branches"]["HEAD"]["target_type"] == "alias"
        tgt_name = snapshot1["branches"]["HEAD"]["target"]
        target = snapshot1["branches"][tgt_name]
        assert target["target_type"] == "revision"
        rev_id = target["target"]
        revision1 = base_api_get(f"revision/{rev_id}/")
        revision2 = api_get(f"revision/{rev_id}/")
        assert filter_obj(revision1) == filter_obj(revision2)

        dir_id = revision1["directory"]

        directory = base_api_get_directory(dir_id)
        mirror_directory = api_get_directory(dir_id)

        for (p1, e1), (p2, e2) in zip(directory, mirror_directory):
            assert p1 == p2
            assert filter_obj(e1) == filter_obj(e2)
            if e1["type"] == "file":
                # here we check the content object is known by both the objstorages
                target = e1["target"]
                base_api_get(f"content/sha1_git:{target}/raw/", verb="HEAD", raw=True)
                api_get(f"content/sha1_git:{target}/raw/", verb="HEAD", raw=True)


def test_mail_sent_to_mirror_operator_on_removal_from_the_main_archive(
    initial_removed,
    origins,
    tiny_git_repo,
    nginx_get,
    mirror_public_storage,
    mirror_api_get,
    removal_identifier,
):
    # ensure the email has been sent
    received_msg = nginx_get("mail/api/v1/message/latest")
    assert received_msg["From"]["Address"] == "swh-mirror@example.org"
    assert {dst["Address"] for dst in received_msg["To"]} == {
        "lucio@example.org",
        "sofia@example.org",
    }
    assert received_msg["Subject"] == (
        "[Action needed] Removal from the main Software Heritage "
        f"archive ({removal_identifier})"
    )

    # now check objects have been masked
    requests = mirror_public_storage.check_output("swh storage masking list-requests")
    assert f"removal-from-main-archive-{removal_identifier}" in requests

    # check below is disabled for now because it's fragile: the list-requests
    # tool may have split lines anywhere... Need an easily parsable output to
    # be checkable
    # assert re.search(
    #    "Removal notification received from main "
    #    rf"archive\s+[(]{removal_identifier}[)]",
    #    requests,
    #    re.MULTILINE,
    # )
    assert "- swh:1:ori:33bf251c0937b1394bc2df185779a75ad0bf3d36" in requests

    # check tiny_git_url is masked, but no other origins
    for _, origin_url in origins:
        if origin_url == tiny_git_repo:
            mirror_api_get(
                f"origin/{quote_plus(origin_url)}/visit/latest/", status_code=403
            )
        else:
            mirror_api_get(f"origin/{quote_plus(origin_url)}/visit/latest/")
    # check individual objects have been masked
    for swhid in initial_removed.removed_swhids:
        if swhid.startswith("swh:1:ori:"):
            continue
        resp = mirror_api_get(f"resolve/{swhid}/", status_code=403)
        assert resp["exception"] == "MaskedObjectException"

    # ensure the GPL license has not been removed
    # the given SWHID is the LICENSE file within swh-py-template (aka tiny_git_repo)
    # which is also in the other git repo (aka swh-counters)
    assert (
        "swh:1:cnt:94a9ed024d3859793618152ea559a168bbcbb5e2"
        not in initial_removed.removed_swhids
    )
    resp = mirror_api_get(
        "resolve/swh:1:cnt:94a9ed024d3859793618152ea559a168bbcbb5e2/", raw=True
    )
    assert resp.status_code == 200
    assert resp.json()["object_type"] == "content"


def test_handle_removal_notification_remove(
    initial_removed,
    origins,
    tiny_git_repo,
    nginx_get,
    mirror_alter_host,
    mirror_public_storage,
    mirror_api_get,
    removal_identifier,
    bundle_path,
):
    # ensure the email has been sent
    received_msg = nginx_get("mail/api/v1/message/latest")
    assert received_msg["From"]["Address"] == "swh-mirror@example.org"
    assert {dst["Address"] for dst in received_msg["To"]} == {
        "lucio@example.org",
        "sofia@example.org",
    }
    assert received_msg["Subject"] == (
        "[Action needed] Removal from the main Software Heritage "
        f"archive ({removal_identifier})"
    )

    # now apply the removal in the mirror
    mirror_alter_host.check_output(
        f"swh alter handle-removal-notification remove {removal_identifier} "
        "--no-recompute "
        "--ignore search "
        "--ignore journal "
        f"--recovery-bundle={bundle_path}"
    )

    # check tiny_git_url is 404, but no other origins
    for _, origin_url in origins:
        if origin_url == tiny_git_repo:
            mirror_api_get(
                f"origin/{quote_plus(origin_url)}/visit/latest/", status_code=404
            )
        else:
            mirror_api_get(f"origin/{quote_plus(origin_url)}/visit/latest/")
    # check individual objects have been removed
    for swhid in initial_removed.removed_swhids:
        if swhid.startswith("swh:1:ori:"):
            continue
        resp = mirror_api_get(f"resolve/{swhid}/", status_code=404)

    # ensure the GPL license has not been removed
    # the given SWHID is the LICENSE file within swh-py-template (aka tiny_git_repo)
    # which is also in the other git repo (aka swh-counters)
    assert (
        "swh:1:cnt:94a9ed024d3859793618152ea559a168bbcbb5e2"
        not in initial_removed.removed_swhids
    )
    resp = mirror_api_get(
        "resolve/swh:1:cnt:94a9ed024d3859793618152ea559a168bbcbb5e2/", raw=True
    )
    assert resp.status_code == 200
    assert resp.json()["object_type"] == "content"


def test_handle_removal_notification_restrict_permanently(
    initial_removed,
    origins,
    tiny_git_repo,
    nginx_get,
    mirror_alter_host,
    mirror_public_storage,
    mirror_api_get,
    removal_identifier,
    bundle_path,
):
    # ensure the email has been sent
    received_msg = nginx_get("mail/api/v1/message/latest")
    assert received_msg["From"]["Address"] == "swh-mirror@example.org"
    assert {dst["Address"] for dst in received_msg["To"]} == {
        "lucio@example.org",
        "sofia@example.org",
    }
    assert received_msg["Subject"] == (
        "[Action needed] Removal from the main Software Heritage "
        f"archive ({removal_identifier})"
    )

    # check tiny_git_url is 403, but no other origins
    for _, origin_url in origins:
        if origin_url == tiny_git_repo:
            mirror_api_get(
                f"origin/{quote_plus(origin_url)}/visit/latest/", status_code=403
            )
        else:
            mirror_api_get(f"origin/{quote_plus(origin_url)}/visit/latest/")

    # now mark the removal in the mirror as permanently restricted
    resp = mirror_alter_host.check_output(
        "swh alter handle-removal-notification "
        f"restrict-permanently {removal_identifier}"
    )

    # check tiny_git_url is still 403, but no other origins
    for _, origin_url in origins:
        if origin_url == tiny_git_repo:
            mirror_api_get(
                f"origin/{quote_plus(origin_url)}/visit/latest/", status_code=403
            )
        else:
            mirror_api_get(f"origin/{quote_plus(origin_url)}/visit/latest/")
    # check individual objects are masked
    for swhid in initial_removed.removed_swhids:
        if swhid.startswith("swh:1:ori:"):
            continue
        resp = mirror_api_get(f"resolve/{swhid}/", status_code=403)

    # ensure the GPL license has not been masked
    # the given SWHID is the LICENSE file within swh-py-template (aka tiny_git_repo)
    # which is also in the other git repo (aka swh-counters)
    assert (
        "swh:1:cnt:94a9ed024d3859793618152ea559a168bbcbb5e2"
        not in initial_removed.removed_swhids
    )
    resp = mirror_api_get(
        "resolve/swh:1:cnt:94a9ed024d3859793618152ea559a168bbcbb5e2/", raw=True
    )
    assert resp.status_code == 200
    assert resp.json()["object_type"] == "content"


def test_handle_removal_notification_dismiss(
    initial_removed,
    origins,
    nginx_get,
    mirror_alter_host,
    mirror_public_storage,
    mirror_api_get,
    removal_identifier,
    bundle_path,
):
    # ensure the email has been sent
    received_msg = nginx_get("mail/api/v1/message/latest")
    assert received_msg["From"]["Address"] == "swh-mirror@example.org"
    assert {dst["Address"] for dst in received_msg["To"]} == {
        "lucio@example.org",
        "sofia@example.org",
    }
    assert received_msg["Subject"] == (
        "[Action needed] Removal from the main Software Heritage "
        f"archive ({removal_identifier})"
    )

    # now dismiss the removal in the mirror
    mirror_alter_host.check_output(
        f"swh alter handle-removal-notification dismiss {removal_identifier}"
    )

    # check all origins, including tiny_git_url, are OK
    for _, origin_url in origins:
        mirror_api_get(f"origin/{quote_plus(origin_url)}/visit/latest/")
    # check individual objects are OK as well
    for swhid in initial_removed.removed_swhids:
        if swhid.startswith("swh:1:ori:"):
            continue
        mirror_api_get(f"resolve/{swhid}/")
