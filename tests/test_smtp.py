# Copyright (C) 2024 The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU General Public License version 3, or any later version
# See top-level LICENSE file for more information

import smtplib
from email.message import EmailMessage

import pytest


@pytest.fixture(scope="module")
def compose_services() -> list[str]:
    return [
        "docker-helper",
        "docker-proxy",
        "smtp",
        "nginx",
    ]


def test_reverse_proxy(compose_files, compose_services, nginx_get) -> None:
    assert nginx_get("mail/api/v1/messages")


def test_send_mail(nginx_get, smtp_port, docker_network_gateway_ip) -> None:
    # nothing in the inbox yet
    with pytest.raises(AssertionError, match=r"Message not found"):
        nginx_get("mail/api/v1/message/latest")
    # send an email
    msg = EmailMessage()
    msg.set_content("test")
    msg["Subject"] = "Test message"
    msg["From"] = "sender@example.com"
    msg["To"] = "recipient@example.com"
    with smtplib.SMTP(docker_network_gateway_ip, port=smtp_port) as conn:
        conn.send_message(msg)
    # read the latest email using mailpit's API
    received_msg = nginx_get("mail/api/v1/message/latest")
    assert received_msg["Subject"] == "Test message"
