# Inherit from the base image
FROM patchwise-base:latest

USER root

# Dump analysis tools, all work on any target architecture
RUN apt-get update && apt-get install -y --no-install-recommends \
    ripgrep \
    jq \
    file \
    xz-utils \
    zstd \
    gdb-multiarch \
    dwarves \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install "pathspec>=0.12" pyelftools

# Scratch space for the agent
RUN mkdir /work && chown patchwise:patchwise /work

USER patchwise
