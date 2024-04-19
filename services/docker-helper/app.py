#!/usr/bin/env python3

# Copyright (C) 2024  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU Affero General Public License version 3, or any later version
# See top-level LICENSE file for more information

import os

import requests
from flask import Flask, abort

app = Flask(__name__)


def get_public_port_and_gateway(service="nginx"):
    # query the docker API to get the port of the edge router
    compose_project_name = os.environ.get("COMPOSE_PROJECT_NAME", "docker")
    # we could think about accessing the docker socket directly here instead of
    # using docker-proxy but there are permission stuff to handle, so...
    containers = requests.get("http://docker-proxy:2375/containers/json").json()
    containers = [
        container
        for container in containers
        if container["Labels"].get("com.docker.compose.project") == compose_project_name
        and container["Labels"].get("com.docker.compose.service") == service
    ]
    port = None
    gateway = None
    if len(containers) == 1:
        edge_ports = [
            p["PublicPort"]
            for p in containers[0]["Ports"]
            if p["IP"] == "0.0.0.0" and p["PrivatePort"] == 80
        ]
        if len(edge_ports) >= 1:
            # return the first one...
            port = edge_ports[0]
        gateway = (
            containers[0]
            .get("NetworkSettings", {})
            .get("Networks", {})
            .get(f"{compose_project_name}_default", {})
            .get("Gateway")
        )
    return port, gateway


@app.route("/public-port/<service>/")
@app.route("/public-port/")
def port_for_service(service="nginx"):
    port, _ = get_public_port_and_gateway(service)
    if port is None:
        abort(404)
    return str(port)


@app.route("/gateway/")
def gateway():
    _, gateway = get_public_port_and_gateway()
    if gateway is None:
        abort(500)
    return gateway


@app.route("/")
def root():
    return "OK"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
