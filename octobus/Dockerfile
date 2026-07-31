FROM node:24-bookworm-slim

ARG TARGETARCH
ARG OCTOBUS_VERSION=0.1.0
ARG CHAITIN_CLI_VERSION=v2606.0.4

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl protobuf-compiler \
    && rm -rf /var/lib/apt/lists/* \
    && npm install --global --ignore-scripts "@chaitin-ai/octobus@${OCTOBUS_VERSION}" \
    && case "${TARGETARCH}" in \
         amd64) archive_sha256="99a0871a9a1c812b520067766b3592edccbe3d44d4f1b942831b4cbe82d8a482" ;; \
         arm64) archive_sha256="55be61691bb71420a1c849e8f7acb12934452d354f790a5125c8e2f5fff54e95" ;; \
         *) echo "unsupported target architecture: ${TARGETARCH}" >&2; exit 1 ;; \
       esac \
    && archive="chaitin-cli_${CHAITIN_CLI_VERSION}_linux_${TARGETARCH}.tar.gz" \
    && curl --fail --location --silent --show-error \
         "https://github.com/chaitin/chaitin-cli/releases/download/${CHAITIN_CLI_VERSION}/${archive}" \
         --output "/tmp/${archive}" \
    && printf '%s  %s\n' "${archive_sha256}" "/tmp/${archive}" | sha256sum --check --strict \
    && tar --extract --gzip --file "/tmp/${archive}" --directory /tmp \
    && install --mode 0555 \
         "/tmp/chaitin-cli_${CHAITIN_CLI_VERSION}_linux_${TARGETARCH}/chaitin-cli" \
         /usr/local/bin/chaitin-cli \
    && rm --recursive --force "/tmp/${archive}" \
         "/tmp/chaitin-cli_${CHAITIN_CLI_VERSION}_linux_${TARGETARCH}"

ENTRYPOINT ["octobus"]
