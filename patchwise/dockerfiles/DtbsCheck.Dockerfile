# Inherit from the base image
FROM patchwise-base:latest

USER root

# Install system dependencies for device tree validation
RUN apt-get update && apt-get install -y --no-install-recommends \
    device-tree-compiler \
    libyaml-dev \
    && rm -rf /var/lib/apt/lists/*

# Install dtschema and related dependencies for dtbs_check
# Use the virtual environment from base image
ENV PATH="/home/patchwise/.venv/bin:$PATH"
RUN pip install --no-cache-dir \
    dtschema \
    jsonschema \
    ruamel.yaml \
    pyyaml

# Verify installation
RUN dt-doc-validate --help && \
    dt-mk-schema --help && \
    dtc --version

USER patchwise
