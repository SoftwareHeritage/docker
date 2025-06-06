ARG REGISTRY=container-registry.softwareheritage.org/swh/infra/swh-apps/
ARG RSVNDUMP=/usr/local/bin/rsvndump
FROM ${REGISTRY}rsvndump-base:latest AS rsvndump_image

# build rage (for swh-alter)
FROM rust:slim-bookworm AS build_rage
RUN cargo install rage

# build yq (stolen from https://github.com/mikefarah/yq/blob/master/Dockerfile)
FROM golang:1.24 AS build_yq

RUN CGO_ENABLED=0 go install -ldflags "-s" github.com/mikefarah/yq/v4@latest

FROM python:3.11

ARG PGDG_REPO=http://apt.postgresql.org/pub/repos/apt
ARG PGDG_GPG_KEY=https://www.postgresql.org/media/keys/ACCC4CF8.asc
ARG PGDG_KEYRING=/usr/share/keyrings/pgdg-archive-keyring.gpg

ARG NODE_REPO=https://deb.nodesource.com/node_20.x
ARG NODE_GPG_KEY=https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key
ARG NODE_KEYRING=/usr/share/keyrings/nodejs-archive-keyring.gpg

ARG YARN_REPO=https://dl.yarnpkg.com/debian/
ARG YARN_GPG_KEY=https://dl.yarnpkg.com/debian/pubkey.gpg
ARG YARN_KEYRING=/usr/share/keyrings/yarnpkg-archive-keyring.gpg

RUN . /etc/os-release && \
  echo "deb [signed-by=${PGDG_KEYRING}] ${PGDG_REPO} ${VERSION_CODENAME}-pgdg main" \
  > /etc/apt/sources.list.d/pgdg.list && \
  curl -fsSL ${PGDG_GPG_KEY} | gpg --dearmor > ${PGDG_KEYRING} && \
  echo "deb [signed-by=${NODE_KEYRING}] ${NODE_REPO} nodistro main" \
  > /etc/apt/sources.list.d/nodejs.list && \
  curl -fsSL ${NODE_GPG_KEY} | gpg --dearmor > ${NODE_KEYRING} && \
  echo "deb [signed-by=${YARN_KEYRING}] ${YARN_REPO} stable main" \
  > /etc/apt/sources.list.d/yarnpkg.list && \
  curl -fsSL ${YARN_GPG_KEY} | gpg --dearmor > ${YARN_KEYRING}

# warning: the py:3.7 image comes with python3.9 installed from debian; do not
# add debian python packages here, they would not be usable for the py37 based
# environment used in this image.
RUN export DEBIAN_FRONTEND=noninteractive && \
  apt-get update && apt-get upgrade -y && \
  apt-get install -y \
  libapr1-dev \
  libaprutil1-dev \
  libcmph-dev \
  libpq-dev \
  librdkafka-dev \
  libsvn-dev \
  libsystemd-dev \
  gcc \
  gettext-base \
  iputils-ping \
  jq \
  pkg-config \
  pv \
  postgresql-client-16 \
  # for rubygems lister
  postgresql-16 \
  wait-for-it \
  ngrep \
  rsync \
  nodejs \
  yarn \
  zstd && \
  apt-get install -y --no-install-recommends \
  opam \
  rpm2cpio \
  nano \
  cpio && \
  apt-get clean && \
  rm -rf /var/lib/apt/lists/*

# Install rsvndump (svn loader related)
COPY --from=rsvndump_image /usr/local/bin/rsvndump /usr/local/bin/rsvndump

# Install rage (for swh-alter)
COPY --from=build_rage /usr/local/cargo/bin/rage /usr/local/cargo/bin/rage-keygen /usr/local/bin
# Install yq
COPY --from=build_yq /go/bin/yq /usr/local/bin

RUN useradd -md /srv/softwareheritage -s /bin/bash swh
USER swh

RUN python3 -m venv /srv/softwareheritage/venv
ENV PATH="/srv/softwareheritage/venv/bin:${PATH}"

RUN --mount=type=cache,uid=1000,target=/srv/softwareheritage/.cache \
    pip install --upgrade pip setuptools wheel
RUN --mount=type=cache,uid=1000,target=/srv/softwareheritage/.cache \
    pip install gunicorn httpie
# cython and configjob are required to install the breeze (bzr) package
RUN --mount=type=cache,uid=1000,target=/srv/softwareheritage/.cache \
    pip install cython configobj

COPY requirements-swh.txt /srv/softwareheritage/
RUN --mount=type=cache,uid=1000,target=/srv/softwareheritage/.cache \
    pip install -r  /srv/softwareheritage/requirements-swh.txt
RUN pip list > /srv/softwareheritage/pip-installed.txt
COPY utils/*.sh /srv/softwareheritage/utils/
RUN mkdir -p /srv/softwareheritage/objects
RUN mkdir -p /srv/softwareheritage/graph
WORKDIR /srv/softwareheritage/
ENV SWH_CONFIG_FILENAME=/srv/softwareheritage/config.yml
ENTRYPOINT ["/srv/softwareheritage/entrypoint.sh"]
