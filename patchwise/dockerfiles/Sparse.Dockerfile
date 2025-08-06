# Inherit from the base image
FROM patchwise-base:latest

USER root

# Install sparse from source
# We chain the commands together and clean up in a single RUN instruction
# to reduce the Docker image layer size.
RUN git clone git://git.kernel.org/pub/scm/devel/sparse/sparse.git /tmp/sparse \
    && cd /tmp/sparse \
    && make \
    && make install \
    && cd / \
    && rm -rf /tmp/sparse

USER patchwise
