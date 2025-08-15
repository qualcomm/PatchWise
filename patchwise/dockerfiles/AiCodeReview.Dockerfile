# Inherit from the base image
FROM patchwise-base:latest

USER root

# AiCodeReview needs clangd for LSP functionality
RUN apt-get update && apt-get install -y --no-install-recommends \
    clangd \
    && rm -rf /var/lib/apt/lists/*

USER patchwise
