FROM node:20-alpine AS build-swh-kc-theme

# build swh theme for keycloak
RUN apk update && \
    apk add --no-cache openjdk17 maven git
ARG SWH_KC_THEME_TAG v0.4.2
RUN git clone https://gitlab.softwareheritage.org/swh/infra/websites/swh-keycloak-theme.git
WORKDIR /swh-keycloak-theme
RUN git checkout ${SWH_KC_THEME_TAG}
RUN yarn install --frozen-lockfile
RUN yarn build-keycloak-theme

FROM registry.access.redhat.com/ubi9 AS ubi-micro-build

# install git and python3 needed in keycloak service entrypoint
RUN mkdir -p /mnt/rootfs
RUN dnf install --installroot /mnt/rootfs git python3 pip curl \
        --releasever 9 --setopt install_weak_deps=false --nodocs -y && \
    dnf --installroot /mnt/rootfs clean all && \
    rpm --root /mnt/rootfs -e --nodeps setup

FROM quay.io/keycloak/keycloak:26.7.5

COPY --from=build-swh-kc-theme /swh-keycloak-theme/dist_keycloak/keycloak-theme-for-kc-all-other-versions.jar /opt/keycloak/providers/
RUN /opt/keycloak/bin/kc.sh build

COPY --from=ubi-micro-build /mnt/rootfs /

# install python-keycloak to execute custom config script in
# keycloak service entrypoint after server is up
RUN pip3 install python-keycloak

# install wait-for-it script
RUN curl https://raw.githubusercontent.com/vishnubob/wait-for-it/master/wait-for-it.sh > ~/wait-for-it.sh
RUN chmod +x ~/wait-for-it.sh
