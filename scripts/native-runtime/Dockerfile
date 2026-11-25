# The AArch64 build environment of the AR9311 receivers' kestrel-gnd runtime
# (scripts/native-runtime.sh). Pinned so the same pins give the same runtime,
# byte for byte, wherever and whenever it is built: the Debian image by
# digest, its packages from snapshot.debian.org as they were on SNAPSHOT.
# Changing either changes the runtime: rebuild it and update the pins in
# br-external/package/kestrel-native/runtime.hash.
FROM debian:trixie-slim@sha256:8aa5a7bf5a1955bddbe7d74fcdd0b91ab30e74362a8b73af672b0481b35b44a0

ARG SNAPSHOT=20261124T000000Z
RUN rm -f /etc/apt/sources.list.d/debian.sources && \
    printf 'deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/%s trixie main\n' "$SNAPSHOT" > /etc/apt/sources.list && \
    printf 'deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/%s trixie-updates main\n' "$SNAPSHOT" >> /etc/apt/sources.list && \
    printf 'deb [check-valid-until=no] http://snapshot.debian.org/archive/debian-security/%s trixie-security main\n' "$SNAPSHOT" >> /etc/apt/sources.list && \
    apt-get -o Acquire::Retries=5 update && \
    apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        build-essential cmake ninja-build pkg-config python3 git ca-certificates \
        libcairo2-dev libfontconfig1-dev linux-libc-dev squashfs-tools file python3-pil && \
    rm -rf /var/lib/apt/lists/*

ARG UID=1000
ARG GID=1000
RUN groupadd -o -g $GID builder && useradd -o -m -u $UID -g $GID builder
USER builder
RUN git config --global --add safe.directory '*'
