# SPDX-License-Identifier: Apache-2.0
# Standalone reproducible container for external replication:
#   docker build -t openie-replicate -f replicate/Dockerfile . && docker run --rm openie-replicate
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        rustc \
        cargo \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 10001 -s /bin/bash replicator

WORKDIR /workspace
COPY . /workspace
RUN mkdir -p /workspace/replicate/out && chown -R replicator:replicator /workspace/replicate/out

USER replicator
ENTRYPOINT ["./replicate/run_replication.sh"]
CMD ["--out", "/workspace/replicate/out"]
