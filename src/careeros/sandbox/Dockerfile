FROM node:22.14.0-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 careeros \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin careeros

USER 10001:10001
WORKDIR /workspace
ENTRYPOINT []
