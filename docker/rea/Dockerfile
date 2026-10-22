# The image `wev rea build-image` builds: Node and rea, nothing else. wev runs it with --user
# <uid>:<gid> and mounts a writable directory at /opt/rea-home; the user below is only the
# default when the image is run some other way.
FROM node:24-slim
ARG REA_VERSION
RUN npm install -g rea-agents@${REA_VERSION}
RUN useradd --create-home --home-dir /opt/rea-home rea
ENV HOME=/opt/rea-home
USER rea
ENTRYPOINT ["rea","mcp"]
