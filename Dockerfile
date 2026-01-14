ARG REGISTRY=container-registry.softwareheritage.org/swh/infra/swh-apps/

FROM softwareheritage/maven-index-exporter:v0.4.1 AS maven_index_exporter_image

# build rust crates
FROM rust:slim-bookworm AS build_rust_base

RUN export DEBIAN_FRONTEND=noninteractive && \
  apt-get update && apt-get upgrade -y && \
  apt-get install -y \
  build-essential clang pkg-config libssl-dev libprotobuf-dev protobuf-compiler curl && \
  apt-get clean && \
  rm -rf /var/lib/apt/lists/*

# install sccache to speedup rust builds
ARG sccache_version=0.12.0
RUN cd /usr/local/bin && \
  curl -sSfL https://github.com/mozilla/sccache/releases/download/v${sccache_version}/sccache-v${sccache_version}-x86_64-unknown-linux-musl.tar.gz | \
  tar --strip-components=1 -xz sccache-v${sccache_version}-x86_64-unknown-linux-musl/sccache

COPY ./env-from-secrets /usr/local/bin

FROM build_rust_base AS build_rust_rage

# rage is required by swh-alter
ARG rage_version=0.11.1
RUN --mount=type=secret,mode=0444,id=SCCACHE_REDIS_ENDPOINT \
    --mount=type=secret,mode=0444,id=SCCACHE_REDIS_PASSWORD \
  env-from-secrets \
      RUSTC_WRAPPER=sccache \
      CARGO_INCREMENTAL=0 \
    cargo install rage@${rage_version} --locked

FROM build_rust_base AS build_rust_swh_graph

# rust crates of swh-graph
ARG swh_graph_version=9.0.2
RUN --mount=type=secret,mode=0444,id=SCCACHE_REDIS_ENDPOINT \
    --mount=type=secret,mode=0444,id=SCCACHE_REDIS_PASSWORD \
  env-from-secrets \
      RUSTC_WRAPPER=sccache \
      CARGO_INCREMENTAL=0 \
    cargo install swh-graph@${swh_graph_version} \
      swh-graph-grpc-server@${swh_graph_version} \
      --all-features --locked

# build yq (stolen from https://github.com/mikefarah/yq/blob/master/Dockerfile)
FROM golang:1.24 AS build_yq

RUN CGO_ENABLED=0 go install -ldflags "-s" github.com/mikefarah/yq/v4@latest

FROM python:3.11 AS install_non_python_dependencies

ARG PGDG_REPO=http://apt.postgresql.org/pub/repos/apt
ARG PGDG_GPG=https://www.postgresql.org/media/keys/ACCC4CF8.asc
ARG PGDG_KEYRING=/usr/share/keyrings/pgdg-archive-keyring.gpg

ARG NODE_REPO=https://deb.nodesource.com/node_20.x
ARG NODE_GPG=https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key
ARG NODE_KEYRING=/usr/share/keyrings/nodejs-archive-keyring.gpg

ARG YARN_REPO=https://dl.yarnpkg.com/debian/
ARG YARN_GPG=https://dl.yarnpkg.com/debian/pubkey.gpg
ARG YARN_KEYRING=/usr/share/keyrings/yarnpkg-archive-keyring.gpg

RUN . /etc/os-release && \
  echo "deb [signed-by=${PGDG_KEYRING}] ${PGDG_REPO} ${VERSION_CODENAME}-pgdg main" \
  > /etc/apt/sources.list.d/pgdg.list && \
  curl -fsSL ${PGDG_GPG} | gpg --dearmor > ${PGDG_KEYRING} && \
  echo "deb [signed-by=${NODE_KEYRING}] ${NODE_REPO} nodistro main" \
  > /etc/apt/sources.list.d/nodejs.list && \
  curl -fsSL ${NODE_GPG} | gpg --dearmor > ${NODE_KEYRING} && \
  echo "deb [signed-by=${YARN_KEYRING}] ${YARN_REPO} stable main" \
  > /etc/apt/sources.list.d/yarnpkg.list && \
  curl -fsSL ${YARN_GPG} | gpg --dearmor > ${YARN_KEYRING}

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
  openjdk-21-jre-headless \
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
  cpio \
  inotify-tools && \
  apt-get clean && \
  rm -rf /var/lib/apt/lists/*

# Install compiled rust binaries (for swh-alter and swh-graph)
COPY --from=build_rust_rage /usr/local/cargo/bin/* /usr/local/bin
COPY --from=build_rust_swh_graph /usr/local/cargo/bin/* /usr/local/bin

# Install yq
COPY --from=build_yq /go/bin/yq /usr/local/bin

# Install maven-index-exporter tool used by the maven lister
COPY --from=maven_index_exporter_image /opt/maven-index-exporter /opt/maven-index-exporter

RUN useradd -md /srv/softwareheritage -s /bin/bash swh

USER swh

RUN python3 -m venv /srv/softwareheritage/venv
ENV PATH="/srv/softwareheritage/venv/bin:${PATH}"

FROM install_non_python_dependencies AS install_python_packages

COPY requirements.txt /srv/softwareheritage/
RUN --mount=type=cache,uid=1000,target=/srv/softwareheritage/.cache \
  pip install -r /srv/softwareheritage/requirements.txt

COPY requirements-swh.txt /srv/softwareheritage/
RUN --mount=type=cache,uid=1000,target=/srv/softwareheritage/.cache \
    # set some CFLAGS to allow compilation of `subvertpy` with GCC>=14
    CFLAGS=-Wno-int-conversion pip install -r /srv/softwareheritage/requirements-swh.txt

RUN pip list > /srv/softwareheritage/pip-installed.txt
COPY utils/*.sh /srv/softwareheritage/utils/
RUN mkdir -p /srv/softwareheritage/objects
RUN mkdir -p /srv/softwareheritage/graph
WORKDIR /srv/softwareheritage/
ENV SWH_CONFIG_FILENAME=/srv/softwareheritage/config.yml
ENTRYPOINT ["/srv/softwareheritage/entrypoint.sh"]
