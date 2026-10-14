# Inherit from the base image
FROM patchwise-base:latest

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    ripgrep \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install "pathspec>=0.12"

# Scratch space for the agent
RUN mkdir /work && chown patchwise:patchwise /work

USER patchwise
