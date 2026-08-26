# Inherit from the base image
FROM patchwise-base:latest

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    ripgrep \
    perl \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install "pathspec>=0.12"

USER patchwise
