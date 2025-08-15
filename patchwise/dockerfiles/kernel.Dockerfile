# Universal kernel setup dockerfile
# This dockerfile adds kernel tree to any tool-specific base image
# Usage: docker build --build-arg TOOL_IMAGE=patchwise-sparse-intermediate --build-arg KERNEL_PATH=... --build-arg CURRENT_COMMIT_SHA=... -f kernel.Dockerfile

ARG TOOL_IMAGE
FROM ${TOOL_IMAGE}

USER root

# Copy the kernel tree into the image
ARG KERNEL_PATH
COPY --chown=patchwise:patchwise $KERNEL_PATH /home/patchwise/kernel

# Checkout the current commit and fix all permissions
ARG CURRENT_COMMIT_SHA
RUN cd /home/patchwise/kernel && \
    git config --global --add safe.directory /home/patchwise/kernel && \
    git reset --hard $CURRENT_COMMIT_SHA && \
    git clean -fdx && \
    chown -R patchwise:patchwise /home/patchwise/kernel

USER patchwise
