# Inherit from the base image
FROM patchwise-base:latest

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    swig \
    meson \
    && rm -rf /var/lib/apt/lists/*

# Build the Python bindings from dtc git. The pylibfdt sdist on PyPI still uses
# the Python 2 C API and no longer compiles; dtc's own copy is current.
RUN pip3 install --no-cache-dir \
    "libfdt @ git+https://git.kernel.org/pub/scm/utils/dtc/dtc.git"

# dtc names its wheel `libfdt`, not the `pylibfdt` dtschema asks for. Install the
# dependencies by hand so pip doesn't rebuild the broken PyPI sdist.
RUN pip3 install --no-cache-dir \
    "ruamel.yaml>0.15.69" \
    "jsonschema>=4.18" \
    rfc3987 \
    && pip3 install --no-cache-dir --no-deps dtschema

RUN pip3 install yamllint

USER patchwise
