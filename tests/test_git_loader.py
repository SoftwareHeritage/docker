# Copyright (C) 2019-2025  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

from urllib.parse import quote_plus

import pytest
from dulwich import porcelain
from dulwich.repo import MemoryRepo

from .utils import grouper


@pytest.fixture(scope="module")
def reset_compose_session():
    return True


@pytest.fixture(
    scope="module",
    params=[["compose.yml"], ["compose.yml", "compose.winery.yml"]],
    ids=["pathslicer", "winery"],
)
def compose_files(request):
    return request.param


@pytest.fixture(scope="module")
def compose_services(compose_files):
    services = [
        "docker-helper",
        "docker-proxy",
        "swh-loader",
        "swh-web",
    ]
    if "compose.winery.yml" in compose_files:
        services.extend(["winery-packer", "winery-cleaner"])
    return services


@pytest.fixture(scope="module")
def origin_urls():
    return [
        (
            "git",
            "https://gitlab.softwareheritage.org/swh/infra/websites/swh-keycloak-theme.git",  # noqa
        ),
        (
            "git",
            "https://gitlab.softwareheritage.org/swh/devel/swh-core.git",  # noqa
        ),
    ]


def test_git_loader(scheduler_host, origins, api_get):
    # check the loaded repos from origins are OK, and nothing is missing
    for origin_type, url in origins:
        assert origin_type == "git"
        print(f"Retrieve references available at {url}")
        repo = MemoryRepo()
        gitrefs = porcelain.fetch(repo, url).refs

        print(f"Look for origin {url}")
        # use quote_plus to prevent urljoin from messing with the 'http://' part of
        # the url
        origin = api_get(f"origin/{quote_plus(url)}/get/")
        assert origin["url"] == url

        visit = api_get(f"origin/{quote_plus(url)}/visit/latest/")
        assert visit["status"] == "full"

        print("Check every identified git ref has been loaded")
        snapshot = api_get(f'snapshot/{visit["snapshot"]}/')

        branches = snapshot["branches"]

        while snapshot["next_branch"] is not None:
            snapshot = api_get(
                f'snapshot/{visit["snapshot"]}/?branches_from={snapshot["next_branch"]}'
            )
            branches.update(snapshot["branches"])

        print(f"snapshot has {len(branches)} branches")

        # check tags
        tag_revision = {}
        tag_release = {}
        for tag, rev in gitrefs.items():
            if tag.startswith(b"refs/tags/"):
                tag_str = tag.decode()
                rev_str = rev.decode()
                obj = repo.get_object(rev)
                if not obj.type_name == b"tag":
                    # ignore lighweigth tags (?)
                    continue
                tag_release[tag_str] = rev_str
                tgt, tgt_id = obj.object
                assert tgt.type_name == b"commit"
                tag_revision[tag_str] = tgt_id.decode()

        for tag, release_id in tag_release.items():
            # check that every release tag listed in the snapshot is known by the
            # archive and consistent
            release = api_get(f"release/{release_id}/")
            assert release["id"] == release_id
            assert release["target_type"] == "revision"
            assert release["target"] == tag_revision[tag]
            # and compare this with what git ls-remote reported
            tag_desc = branches[tag]
            assert tag_desc["target_type"] == "release"
            assert tag_desc["target"] == release_id

        # check all cnt, dir or rev objects; we check only objects accessible
        # from non-filtered refs (should we use
        # swh/loader/git/utils.py:ignore_branch_name here?)
        used_branches = []
        # check every fetched branch is present in the snapshot
        for branch_name in gitrefs.keys():
            if branch_name.endswith(b"^{}"):
                continue
            if branch_name.startswith(b"refs/merge-requests") and branch_name.endswith(
                b"/merge"
            ):
                continue
            if branch_name.startswith(b"refs/pull/") and branch_name.endswith(
                b"/merge"
            ):
                continue
            if branch_name.startswith((b"refs/pipelines/", b"refs/changes/")):
                continue
            used_branches.append(branch_name)

        accessible_revs = set(
            we.commit.id
            for we in repo.get_walker(
                include=[repo[gitrefs[bn]].id for bn in used_branches]
            )
        )
        all_objs = set(repo.object_store)
        rp = repo.object_store.get_reachability_provider()
        accessible_trees = set(
            rp.get_tree_objects([repo[rev].tree for rev in accessible_revs])
        )
        # we will no check anything that is not accessible from a 'valid'
        # ref/branch name
        ignored_objs = all_objs - (accessible_revs | accessible_trees)

        print("Check every git object is known by the archive")
        for batch in grouper(
            (obj for obj in repo.object_store if obj not in ignored_objs), 1000
        ):
            swhids = []
            for sha1 in batch:
                obj = repo.get_object(sha1)
                sha1_str = sha1.decode()
                if obj.type_name == b"blob":
                    swhids.append(f"swh:1:cnt:{sha1_str}")
                elif obj.type_name == b"commit":
                    swhids.append(f"swh:1:rev:{sha1_str}")
                elif obj.type_name == b"tree":
                    swhids.append(f"swh:1:dir:{sha1_str}")
            known = api_get("known/", verb="post", json=swhids)
            missing = [k for k, v in known.items() if v["known"] is not True]
            assert not missing, missing
