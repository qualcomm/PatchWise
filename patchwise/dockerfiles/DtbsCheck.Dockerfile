# Inherit from the base image
FROM patchwise-base:latest

USER root

# Install system dependencies for device tree validation
RUN apt-get update && apt-get install -y --no-install-recommends \
    device-tree-compiler \
    libyaml-dev \
    swig \
    meson \
    && rm -rf /var/lib/apt/lists/*

# Install dtschema and related dependencies for dtbs_check
# Use the virtual environment from base image
ENV PATH="/home/patchwise/.venv/bin:$PATH"

# Build the Python bindings from dtc git. The pylibfdt sdist on PyPI still uses
# the Python 2 C API and no longer compiles; dtc's own copy is current.
RUN pip install --no-cache-dir \
    "libfdt @ git+https://git.kernel.org/pub/scm/utils/dtc/dtc.git"

# dtc names its wheel `libfdt`, not the `pylibfdt` dtschema asks for. Install the
# dependencies by hand so pip doesn't rebuild the broken PyPI sdist.
RUN pip install --no-cache-dir \
    "ruamel.yaml>0.15.69" \
    "jsonschema>=4.18" \
    rfc3987 \
    pyyaml \
    && pip install --no-cache-dir --no-deps dtschema

# Verify installation
RUN dt-doc-validate --help && \
    dt-mk-schema --help && \
    dtc --version

USER patchwise
