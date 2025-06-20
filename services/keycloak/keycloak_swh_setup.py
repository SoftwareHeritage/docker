#!/usr/bin/env python3

# Copyright (C) 2020-2024  The Software Heritage developers
# See the AUTHORS file at the top-level directory of this distribution
# License: GNU Affero General Public License version 3, or any later version
# See top-level LICENSE file for more information

import logging

import requests
from keycloak import KeycloakAdmin

SERVER_URL = "http://localhost:8080/keycloak/auth/"
REALM_NAME = "SoftwareHeritage"

CLIENT_WEBAPP_NAME = "swh-web"
CLIENT_DEPOSIT_NAME = "swh-deposit"
CLIENT_COARNOTIFY_NAME = "swh-coarnotify"

ADMIN = {"username": "admin", "password": "admin"}


logger = logging.getLogger(__name__)


def get_frontend_url():
    # query the docker API to get the port of the edge router
    resp = requests.get("http://docker-helper/public-port/")
    if resp.status_code == 200:
        port = resp.json()
        return f"http://localhost:{port}/keycloak/auth/"

    return SERVER_URL


def assign_client_base_url(keycloak_admin, client_name, base_url):
    client_data = {"baseUrl": base_url, "clientId": client_name}
    client_id = keycloak_admin.get_client_id(client_name)
    keycloak_admin.update_client(client_id, client_data)


def assign_client_role_to_user(keycloak_admin, client_name, client_role, username):
    client_id = keycloak_admin.get_client_id(client_name)
    user_role = keycloak_admin.get_client_role(client_id, client_role)
    user_id = keycloak_admin.get_user_id(username)
    keycloak_admin.assign_client_role(user_id, client_id, user_role)


def assign_realm_roles_to_user(keycloak_admin, realm_roles, username):
    roles = []
    for realm_role in realm_roles:
        roles.append(keycloak_admin.get_realm_role(realm_role))
    user_id = keycloak_admin.get_user_id(username)
    keycloak_admin.assign_realm_roles(user_id, roles=roles)


def assign_client_roles_to_user(keycloak_admin, client_name, client_roles, username):
    for client_role in client_roles:
        assign_client_role_to_user(keycloak_admin, client_name, client_role, username)


def create_user(keycloak_admin, user_data):
    try:
        keycloak_admin.create_user(user_data)
    except Exception as e:
        logger.warning(f"User already created: {e}, skipping.")


def create_client_roles(keycloak_admin, client_name, client_roles):
    for client_role in client_roles:
        try:
            keycloak_admin.create_client_role(
                client_name, payload={"name": client_role}
            )
        except Exception as e:
            logger.warning(f"Client role already created: {e}, skipping.")


def create_realm_roles(keycloak_admin, realm_roles):
    for realm_role in realm_roles:
        try:
            keycloak_admin.create_realm_role(payload={"name": realm_role})
        except Exception as e:
            logger.warning(f"Realm role already created: {e}, skipping.")


# login as admin in master realm
KEYCLOAK_ADMIN = KeycloakAdmin(SERVER_URL, ADMIN["username"], ADMIN["password"])

# update master realm clients base urls as we use a reverse proxy
assign_client_base_url(
    KEYCLOAK_ADMIN, "account", "/keycloak/auth/realms/master/account"
)

assign_client_base_url(
    KEYCLOAK_ADMIN,
    "security-admin-console",
    "/keycloak/auth/admin/master/console/index.html",
)

KEYCLOAK_ADMIN.update_realm(
    "master",
    payload={
        "loginTheme": "swh",
        "accountTheme": "swh",
        "adminTheme": "swh",
    },
)

# create swh realm
KEYCLOAK_ADMIN.create_realm(
    payload={
        "id": REALM_NAME,
        "realm": REALM_NAME,
        "displayName": "Software Heritage",
        "rememberMe": True,
        "attributes": {"frontendUrl": get_frontend_url()},
        "enabled": True,
        "loginTheme": "swh",
        "accountTheme": "swh",
        "adminTheme": "swh",
        "registrationAllowed": True,
        "verifyEmail": True,
        "smtpServer": {
            "port": "1025",
            "host": "smtp",
            "from": "keycloak-swh@docker",
            "fromDisplayName": "Keycloak SWH @ docker",
        },
    },
    skip_exists=True,
)

# set swh realm name in order to create users in it
KEYCLOAK_ADMIN.realm_name = REALM_NAME

# update swh realm clients base urls as we use a reverse proxy
assign_client_base_url(
    KEYCLOAK_ADMIN, "account", f"/keycloak/auth/realms/{REALM_NAME}/account"
)

assign_client_base_url(
    KEYCLOAK_ADMIN,
    "security-admin-console",
    f"/keycloak/auth/admin/{REALM_NAME}/console/index.html",
)

# create an admin user in the swh realm
user_data = {
    "email": "admin@example.org",
    "username": ADMIN["username"],
    "firstName": ADMIN["username"],
    "lastName": ADMIN["username"],
    "credentials": [
        {"value": ADMIN["password"], "type": "password", "temporary": False}
    ],
    "enabled": True,
    "emailVerified": True,
}

create_user(KEYCLOAK_ADMIN, user_data)

# assign realm admin roles to created user
realm_management_roles = [
    "view-users",
    "view-events",
    "view-identity-providers",
    "manage-identity-providers",
    "create-client",
    "query-clients",
    "query-realms",
    "manage-events",
    "view-clients",
    "manage-realm",
    "impersonation",
    "manage-clients",
    "view-authorization",
    "query-users",
    "view-realm",
    "manage-authorization",
    "manage-users",
    "query-groups",
]

assign_client_roles_to_user(
    KEYCLOAK_ADMIN, "realm-management", realm_management_roles, ADMIN["username"]
)


# login as admin in swh realm
KEYCLOAK_ADMIN = KeycloakAdmin(
    SERVER_URL, ADMIN["username"], ADMIN["password"], REALM_NAME
)

for client_name, redirect_uris in [
    (
        CLIENT_WEBAPP_NAME,
        [
            "http://localhost:5004/*",
            "http://localhost/*",
            "http://localhost:5013/*",
            "http://localhost/graphql",
        ],
    ),
    (CLIENT_DEPOSIT_NAME, ["http://localhost:5006/*"]),
    (CLIENT_COARNOTIFY_NAME, ["http://localhost:5009/*"]),
]:
    # create swh-web public client
    KEYCLOAK_ADMIN.create_client(
        payload={
            "id": client_name,
            "clientId": client_name,
            "surrogateAuthRequired": False,
            "enabled": True,
            "redirectUris": redirect_uris,
            "bearerOnly": False,
            "consentRequired": False,
            "standardFlowEnabled": True,
            "implicitFlowEnabled": False,
            "directAccessGrantsEnabled": True,
            "serviceAccountsEnabled": False,
            "publicClient": True,
            "frontchannelLogout": False,
            "protocol": "openid-connect",
            "fullScopeAllowed": True,
            "protocolMappers": [
                {
                    "name": "user groups",
                    "protocol": "openid-connect",
                    "protocolMapper": "oidc-group-membership-mapper",
                    "consentRequired": False,
                    "config": {
                        "full.path": True,
                        "userinfo.token.claim": True,
                        "id.token.claim": True,
                        "access.token.claim": True,
                        "claim.name": "groups",
                        "jsonType.label": "String",
                    },
                },
                {
                    "name": "audience",
                    "protocol": "openid-connect",
                    "protocolMapper": "oidc-audience-mapper",
                    "consentRequired": False,
                    "config": {
                        "included.client.audience": client_name,
                        "id.token.claim": True,
                        "access.token.claim": True,
                    },
                },
            ],
        },
        skip_exists=True,
    )

# create staff group
KEYCLOAK_ADMIN.create_group(
    payload={
        "name": "staff",
    },
    skip_exists=True,
)

GROUPS = KEYCLOAK_ADMIN.get_groups()

ADMIN_USER_ID = KEYCLOAK_ADMIN.get_user_id(username=ADMIN["username"])

for GROUP in GROUPS:
    if GROUP["name"] == "staff":
        KEYCLOAK_ADMIN.group_user_add(ADMIN_USER_ID, GROUP["id"])
        break

# create webapp client roles

WEB_API_THROTTLING_EXEMPTED_ROLE_NAME = "swh.web.api.throttling_exempted"
WEB_API_GRAPH_ROLE_NAME = "swh.web.api.graph"
VAULT_GIT_BARE_UI_ROLE_NAME = "swh.vault.git_bare.ui"
WEB_ADMIN_LIST_DEPOSITS_ROLE_NAME = "swh.web.admin.list_deposits"
WEB_API_SAVE_BULK = "swh.web.api.save_bulk"

create_client_roles(
    KEYCLOAK_ADMIN,
    CLIENT_WEBAPP_NAME,
    [
        WEB_API_THROTTLING_EXEMPTED_ROLE_NAME,
        WEB_API_GRAPH_ROLE_NAME,
        VAULT_GIT_BARE_UI_ROLE_NAME,
        WEB_ADMIN_LIST_DEPOSITS_ROLE_NAME,
        WEB_API_SAVE_BULK,
    ],
)

DEPOSIT_API_ROLE_NAME = "swh.deposit.api"

# create deposit client roles
create_client_roles(
    KEYCLOAK_ADMIN,
    CLIENT_DEPOSIT_NAME,
    [DEPOSIT_API_ROLE_NAME],
)

# create some test users
for user_data in [
    {
        "email": "john.doe@example.org",
        "username": "johndoe",
        "firstName": "John",
        "lastName": "Doe",
        "credentials": [
            {"value": "johndoe-swh", "type": "password", "temporary": False}
        ],
        "enabled": True,
        "emailVerified": True,
    },
    {
        "email": "jane.doe@example.org",
        "username": "janedoe",
        "firstName": "Jane",
        "lastName": "Doe",
        "credentials": [
            {"value": "janedoe-swh", "type": "password", "temporary": False}
        ],
        "enabled": True,
        "emailVerified": True,
    },
    {
        "email": "test@swh.org",
        "username": "test",
        "firstName": "Test",
        "lastName": "aibot",
        "credentials": [{"value": "test", "type": "password", "temporary": False}],
        "enabled": True,
        "emailVerified": True,
    },
    {
        "email": "ambassador@swh.org",
        "username": "ambassador",
        "firstName": "ambassador",
        "lastName": "ambassador",
        "credentials": [
            {"value": "ambassador", "type": "password", "temporary": False}
        ],
        "enabled": True,
        "emailVerified": True,
    },
]:
    create_user(KEYCLOAK_ADMIN, user_data)


assign_client_roles_to_user(
    KEYCLOAK_ADMIN, CLIENT_DEPOSIT_NAME, [DEPOSIT_API_ROLE_NAME], "test"
)
assign_client_roles_to_user(
    KEYCLOAK_ADMIN, CLIENT_WEBAPP_NAME, [WEB_ADMIN_LIST_DEPOSITS_ROLE_NAME], "test"
)
assign_client_roles_to_user(
    KEYCLOAK_ADMIN, CLIENT_WEBAPP_NAME, [WEB_API_SAVE_BULK], "johndoe"
)

AMBASSADOR_ROLE_NAME = "swh.ambassador"

# create SoftwareHeritage realm roles
create_realm_roles(
    KEYCLOAK_ADMIN,
    [AMBASSADOR_ROLE_NAME],
)

assign_realm_roles_to_user(KEYCLOAK_ADMIN, [AMBASSADOR_ROLE_NAME], "ambassador")


# swh-coarnotify admin role
COARNOTIFY_ADMIN_ROLE_NAME = "swh.coarnotify.server"
create_client_roles(
    KEYCLOAK_ADMIN,
    CLIENT_COARNOTIFY_NAME,
    [COARNOTIFY_ADMIN_ROLE_NAME],
)
