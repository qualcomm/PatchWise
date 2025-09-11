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
    bc \
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

# Set up Python virtual environment
RUN python3 -m venv /home/patchwise/.venv
ENV PATH="/home/patchwise/.venv/bin:$PATH"

# Create initialization script for shared build directory
COPY <<EOF /home/patchwise/init-build-dir.sh
#!/bin/bash
set -e
echo "Initializing shared build directory..."
mkdir -p /shared/build
chown -R patchwise:patchwise /shared/build
chmod -R 755 /shared/build
echo "Build directory initialized successfully"
EOF

RUN chmod +x /home/patchwise/init-build-dir.sh

USER patchwise
