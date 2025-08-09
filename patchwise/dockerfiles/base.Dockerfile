# Use a base image with common development tools
FROM debian:bookworm-slim

# Ensure all packages are updated to the latest security patches
# RUN apt-get update && apt-get upgrade -y --no-install-recommends && rm -rf /var/lib/apt/lists/*

# Install essential build tools and dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    libssl-dev \
    libelf-dev \
    fakeroot \
    ca-certificates \
    python3-pip \
    python3-dev \
    patch \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    lsb-release \
    software-properties-common \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y --no-install-recommends \
    clang \
    llvm \
    lld \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-full \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y --no-install-recommends \
    flex \
    bison \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*


# Set up a non-root user
RUN useradd -m -s /bin/bash patchwise

# Set the working directory
WORKDIR /home/patchwise

# Set up the build directory
RUN mkdir /home/patchwise/build && chown -R patchwise:patchwise /home/patchwise/build

# Copy the kernel tree into the image
ARG KERNEL_PATH
COPY --chown=patchwise:patchwise $KERNEL_PATH /home/patchwise/kernel

# Checkout the current commit
USER root
ARG CURRENT_COMMIT_SHA
RUN cd /home/patchwise/kernel && \
    git config --global --add safe.directory /home/patchwise/kernel && \
    git reset --hard $CURRENT_COMMIT_SHA && \
    git clean -fdx

RUN python3 -m venv /home/patchwise/.venv
ENV PATH="/home/patchwise/.venv/bin:$PATH"


USER patchwise
