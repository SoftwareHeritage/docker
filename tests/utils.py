# Copyright (C) 2019-2024  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

import dataclasses
import hashlib
import itertools
import logging
import random
import time
from os.path import join
from typing import Any, Callable, Generator, List, Mapping, Optional, Tuple
from urllib.parse import urljoin

import requests
import testinfra
import yaml
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


def grouper(iterable, n):
    # copied from swh.core.utils
    args = [iter(iterable)] * n
    stop_value = object()
    for _data in itertools.zip_longest(*args, fillvalue=stop_value):
        yield (d for d in _data if d is not stop_value)


# Utility functions
def api_get(
    baseurl: str,
    path: str,
    verb: str = "GET",
    session: Optional[requests.Session] = None,
    status_code: int = 200,
    raw: Optional[bool] = None,
    **kwargs,
):
    """Query the API at path and return the json result or raise an AssertionError

    args:
        baseurl: the base URL to query

        path: the path of the query

        verb: the HTTP verb of the query

        session: an optional requests.Session

        status_code: the expected status code (AssertionError will be raised if
            the response code is different from this status_code).

        raw: if True, return the Response object; if False, return the json
            structures (aka response.json()); if not given, its value will be
            set accurding the verb: True for a HEAD, False otherwise.

        **kwargs: Any other named argument will be passes to session.request().
    """
    if session is None:
        session = requests.Session()
    assert path[0] != "/", "you probably do not want that..."
    url = urljoin(baseurl, path)
    resp = session.request(verb, url, **kwargs)
    assert resp.status_code == status_code, f"failed to retrieve {url}: {resp.text}"
    if raw is None:
        raw = verb.upper() in ("HEAD",)
    if raw:
        return resp
    return resp.json()


def retry_until_success(
    operation: Callable[..., bool],
    error_message="Operation did not succeed after multiple retries",
    max_attempts: int = 120,
) -> Any:
    for _ in range(max_attempts):
        ret = operation()
        if ret:
            return ret
        time.sleep(1)
    else:
        raise AssertionError(error_message)


def api_poll(
    baseurl: str,
    path: str,
    session: requests.Session,
    verb: str = "GET",
    **kwargs,
):
    """Poll the API at path until it returns an OK result"""
    session.mount(
        "http://",
        HTTPAdapter(
            max_retries=Retry(
                total=60,
                backoff_factor=0.1,
                status_forcelist=[404, 413, 429, 502, 503, 504],
            )
        ),
    )
    url = urljoin(baseurl, path)
    resp = session.request(verb, url, **kwargs)
    session.mount("http://", HTTPAdapter())
    if not resp.ok:
        raise AssertionError(f"Polling {url} failed")
    return resp


def api_get_directory(
    apiurl: str,
    dirid: str,
    currentpath: str = "",
    session=None,
) -> Generator[Tuple[str, Mapping], None, None]:
    """Recursively retrieve directory description from the archive"""
    directory = api_get(apiurl, f"directory/{dirid}/", session=session)
    for direntry in directory:
        path = join(currentpath, direntry["name"])
        if direntry["type"] != "dir":
            yield (path, direntry)
        else:
            yield from api_get_directory(
                apiurl, direntry["target"], path, session=session
            )


def generate_bearer_token(webapp_host, username, password):
    try:
        return webapp_host.check_output(
            f"swh auth -u http://nginx/keycloak/auth/ generate-token {username} "
            f"-p {password}"
        )
    except AssertionError:
        return False


def compose_host_for_service(docker_compose, service):
    docker_id = docker_compose.check_compose_output(
        f"ps {service} --format '{{{{.ID}}}}'"
    )
    if docker_id:
        return testinfra.get_host("docker://" + docker_id)


@dataclasses.dataclass
class RemovalOperation:
    identifier: str
    bundle_path: str
    origins: List[str]
    removed_swhids: List[str] = dataclasses.field(default_factory=list)
    referencing: List[str] = dataclasses.field(default_factory=list)
    _removed_content_sha1s: Optional[List[bytes]] = None

    def get_removed_content_sha1s(self, host):
        if self._removed_content_sha1s is None:
            self._removed_content_sha1s = []
            # Computing the SHA1 of content objects from the recovery bundle
            # is a very slow operation. So let’s only take a random sample
            # of the content SWHIDS.
            some_content_swhids = random.sample(
                [
                    swhid
                    for swhid in self.removed_swhids
                    if swhid.startswith("swh:1:cnt:")
                ],
                k=5,
            )
            logger.debug(
                "random content sha1s picked %s", ", ".join(some_content_swhids)
            )
            for swhid in some_content_swhids:
                cmd = host.run(
                    f"swh alter recovery-bundle extract-content "
                    "--identity /srv/softwareheritage/age-identities.txt --output - "
                    f"'{self.bundle_path}' '{swhid}'"
                )
                assert cmd.succeeded, f"extract-content failed! {cmd.stderr}"
                sha1 = hashlib.sha1(cmd.stdout_bytes).hexdigest()
                logger.debug("%s data SHA1: %s", swhid, sha1)
                self._removed_content_sha1s.append(sha1)
        return self._removed_content_sha1s

    def run_in(self, host):
        remove_output = host.check_output(
            "echo y | swh alter remove "
            f"--identifier '{self.identifier}' "
            f"--recovery-bundle '{self.bundle_path}' "
            f"{' '.join(self.origins)}"
        )
        logger.debug(remove_output)
        dump = host.check_output(
            f"swh alter recovery-bundle info --dump-manifest '{self.bundle_path}'"
        )
        manifest = yaml.safe_load(dump)
        logger.debug("%s manifest %s", self.identifier, manifest)
        self.removed_swhids = manifest["swhids"]
        if int(manifest["version"]) >= 3:
            assert self.origins == manifest["requested"]
            self.referencing = manifest["referencing"]
