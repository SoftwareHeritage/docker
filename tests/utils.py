# Copyright (C) 2019-2023  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

import itertools
import time
from os.path import join
from typing import Generator, Mapping, Optional, Tuple
from urllib.parse import urljoin

import requests


def grouper(iterable, n):
    # copied from swh.core.utils
    args = [iter(iterable)] * n
    stop_value = object()
    for _data in itertools.zip_longest(*args, fillvalue=stop_value):
        yield (d for d in _data if d is not stop_value)


# Utility functions
def api_get(baseurl: str, path: str, verb: str = "GET", session=None, **kwargs):
    """Query the API at path and return the json result or raise an
    AssertionError"""
    if session is None:
        session = requests
    assert path[0] != "/", "you probably do not want that..."
    url = urljoin(baseurl, path)
    resp = session.request(verb, url, **kwargs)
    assert resp.status_code == 200, f"failed to retrieve {url}: {resp.text}"
    if verb.lower() == "head":
        return resp
    else:
        return resp.json()


def api_poll(
    baseurl: str,
    path: str,
    verb: str = "GET",
    session=None,
    rewrite_redirect: Optional[Tuple[str, str]] = None,
    **kwargs,
):
    """Poll the API at path until it returns an OK result"""
    if session is None:
        session = requests
    url = urljoin(baseurl, path)
    if rewrite_redirect is not None:
        kwargs["allow_redirects"] = False
    for _ in range(60):
        resp = session.request(verb, url, **kwargs)
        if resp.ok:
            if rewrite_redirect and resp.status_code == 302:
                url = resp.headers["Location"].replace(*rewrite_redirect)
            else:
                break
        time.sleep(1)
    else:
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
