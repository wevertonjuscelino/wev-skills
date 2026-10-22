# The blank Linux machine the linux-core end-to-end scenario installs into: Python 3.14, git,
# curl, Node and npm, and a non-root user. Nothing else, no secrets. The clone is mounted
# read-only at /src when the container runs.
FROM python:3.14-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates nodejs npm \
    && apt-get clean
RUN useradd --create-home --shell /bin/bash runner
ENV PYTHONDONTWRITEBYTECODE=1
USER runner
WORKDIR /home/runner
