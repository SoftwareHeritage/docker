# Copyright (C) 2019-2023  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

import hashlib
import io
from os.path import join
import tarfile
from typing import List
from urllib.parse import quote_plus

import pytest

from .conftest import service_url


@pytest.fixture(
    scope="module",
    params=[
        [
            "docker-compose.yml",
            "docker-compose.vault.yml",
            "docker-compose.vault-azure.yml",
        ],
        ["docker-compose.yml", "docker-compose.vault.yml"],
    ],
    ids=["azure_cache", "local_cache"],
)
def compose_files(request) -> List[str]:
    return request.param


def test_vault_directory(
    docker_compose, origins, compose_files, api_get, api_poll, api_get_directory
):
    # retrieve the root directory of the master branch of the ingested git
    # repository (by the git_origin fixture)

    for _, origin_url in origins:
        visit = api_get(f"origin/{quote_plus(origin_url)}/visit/latest/")
        snapshot = api_get(f'snapshot/{visit["snapshot"]}/')

        assert snapshot["branches"]["HEAD"]["target_type"] == "alias"
        tgt_name = snapshot["branches"]["HEAD"]["target"]
        target = snapshot["branches"][tgt_name]
        assert target["target_type"] == "revision"
        rev_id = target["target"]

        revision = api_get(f"revision/{rev_id}/")
        dir_id = revision["directory"]
        swhid = f"swh:1:dir:{dir_id}"

        # now cook it
        cook = api_get(f"vault/flat/{swhid}/", "POST")
        assert cook["swhid"] == swhid
        assert cook["fetch_url"].endswith(f"vault/flat/{swhid}/raw/")

        # while it's cooking, get the directory tree from the archive
        directory = api_get_directory(dir_id)

        # retrieve the cooked tar file
        if "docker-compose.vault-azure.yml" in compose_files:
            # if we use azure, we need to hack the 301 handling to rewrite the
            # Location url to get the artifact from. This is needed because the
            # http://azurite:10000/ url serving as azure endpoint is only
            # available from the compose network, not from the host.
            azure_url = service_url(docker_compose, "azurite", 10000)
            rewrite_redirect = ("http://azurite:10000/", f"{azure_url}/")
        else:
            rewrite_redirect = None
        resp = api_poll(f"vault/flat/{swhid}/raw/", rewrite_redirect=rewrite_redirect)
        tarf = tarfile.open(fileobj=io.BytesIO(resp.content))

        # and check the tarfile seems ok wrt. 'directory'
        assert tarf.getnames()[0] == swhid
        tarfiles = {t.name: t for t in tarf.getmembers()}

        for fname, fdesc in directory:
            tfinfo = tarfiles.get(join(swhid, fname))
            assert tfinfo, f"Missing path {fname} in retrieved tarfile"
            if fdesc["type"] == "file":
                if tfinfo.issym():
                    # checksum was computed from targeted path for symlink
                    fdata = tfinfo.linkname.encode()
                else:
                    # symlink has no size in tar archive so this test fails
                    assert (
                        fdesc["length"] == tfinfo.size
                    ), f"File {fname}: length mismatch"
                    fdata = tarf.extractfile(tfinfo).read()

                for algo in fdesc["checksums"]:
                    if algo not in hashlib.algorithms_available:
                        continue
                    hash = hashlib.new(algo, fdata).hexdigest()
                    assert (
                        hash == fdesc["checksums"][algo]
                    ), f"File {fname}: {algo} mismatch"
            # XXX what to check for dir or rev?

        # check that if we ask a second time this directory, it returns the same
        # and does not cook it again
        recook = api_get(f"vault/flat/{swhid}/", "POST")
        assert recook["swhid"] == swhid
        assert recook["id"] == cook["id"]
        assert recook["status"] == "done"  # no need to wait for this to be true


def test_vault_git_bare(
    host,
    docker_compose,
    origins,
    compose_files,
    tmp_path,
    api_get,
    api_poll,
    api_get_directory,
):
    # retrieve the revision of the master branch of the ingested git
    # repository (by the git_origin fixture)

    for _, origin_url in origins:
        visit = api_get(f"origin/{quote_plus(origin_url)}/visit/latest/")

        snapshot = api_get(f'snapshot/{visit["snapshot"]}/')
        assert snapshot["branches"]["HEAD"]["target_type"] == "alias"
        tgt_name = snapshot["branches"]["HEAD"]["target"]
        target = snapshot["branches"][tgt_name]
        assert target["target_type"] == "revision"
        rev_id = target["target"]

        swhid = f"swh:1:rev:{rev_id}"
        revision = api_get(f"revision/{rev_id}/")
        dir_id = revision["directory"]

        # now cook it
        cook = api_get(f"vault/git-bare/{swhid}/", "POST")
        assert cook["swhid"] == swhid
        assert cook["fetch_url"].endswith(f"vault/git-bare/{swhid}/raw/")

        # while it's cooking, get the directory tree from the archive
        directory = api_get_directory(dir_id)

        # retrieve the cooked tar file
        if "docker-compose.vault-azure.yml" in compose_files:
            # if we use azure, we need to hack the 301 handling to rewrite the
            # Location url to get the artifact from. This is needed because the
            # http://azurite:10000/ url serving as azure endpoint is only
            # available from the compose network, not from the host.
            azure_url = service_url(docker_compose, "azurite", 10000)
            rewrite_redirect = ("http://azurite:10000/", f"{azure_url}/")
        else:
            rewrite_redirect = None
        resp = api_poll(
            f"vault/git-bare/{swhid}/raw/", rewrite_redirect=rewrite_redirect
        )
        tarf = tarfile.open(fileobj=io.BytesIO(resp.content))
        assert tarf.getnames()[0] == f"{swhid}.git"

        # extract it in a tmp file and attempt to git clone it
        tarf.extractall(path=tmp_path)
        repo = tmp_path / swhid
        host.run_test(f"git clone {tmp_path/swhid}.git {repo}")
        # check a few basic git stuff
        assert host.check_output(f"git -C {repo} branch") == "* master"
        assert host.check_output(f"git -C {repo} rev-parse HEAD") == rev_id
        host.run_test(f"git -C {repo} log")

        # check the working directory matches dir_id content from the archive
        for fname, fdesc in directory:
            if fdesc["type"] == "file":
                assert (repo / fname).is_file()
                if fdesc["perms"] == 0o120000:
                    # it's a symlink; see DentryPerms in swh.model
                    fdata = bytes((repo / fname).readlink())
                else:
                    # it's an actual file
                    fdata = (repo / fname).read_bytes()
                for algo in fdesc["checksums"]:
                    if algo not in hashlib.algorithms_available:
                        continue
                    hash = hashlib.new(algo, fdata).hexdigest()
                    assert (
                        hash == fdesc["checksums"][algo]
                    ), f"File {fname}: {algo} mismatch"
            elif fdesc["type"] == "dir":
                assert (repo / fname).is_dir()
            elif fdesc["type"] == "rev":
                # TODO
                pass
            else:
                raise AssertionError(
                    f"Unexpected directory entry type {fdesc['type']} from {fdesc}"
                )

        # check that if we ask a second time this directory, it returns the same
        # and does not cook it again
        recook = api_get(f"vault/git-bare/{swhid}/", "POST")
        assert recook["swhid"] == swhid
        assert recook["id"] == cook["id"]
        assert recook["status"] == "done"  # no need to wait for this to be true
