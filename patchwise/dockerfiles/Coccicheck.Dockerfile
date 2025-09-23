# Inherit from the base image
FROM patchwise-base:latest

USER root

# Install coccinelle
RUN apt-get update && apt-get install -y --no-install-recommends \
    coccinelle \
    && rm -rf /var/lib/apt/lists/*

USER patchwise
