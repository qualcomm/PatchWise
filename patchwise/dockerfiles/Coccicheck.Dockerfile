# Inherit from the base image
FROM patchwise-base:latest

USER root

# Install coccinelle
# Install OCaml native compiler (it is used for some semantic patches)
RUN apt-get update && apt-get install -y --no-install-recommends \
    coccinelle \
    ocaml-native-compilers \
    && rm -rf /var/lib/apt/lists/*

USER patchwise
