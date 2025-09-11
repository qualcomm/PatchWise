# Inherit from the base image
FROM patchwise-base:latest

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    llvm-dev \
    bc \
    # libllvm \
    # clang-dev \
    && rm -rf /var/lib/apt/lists/*

# Install LLVM development headers required for sparse compilation
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     llvm-dev \
#     libllvm-dev \
#     && rm -rf /var/lib/apt/lists/*
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     llvm-14-dev \
#     libllvm-14-dev \
#     && rm -rf /var/lib/apt/lists/*

# RUN wget https://apt.llvm.org/llvm.sh && chmod +x ./llvm.sh && ./llvm.sh 14

# Install sparse from source
# We chain the commands together and clean up in a single RUN instruction
# to reduce the Docker image layer size.
RUN git clone git://git.kernel.org/pub/scm/devel/sparse/sparse.git /tmp/sparse \
    && cd /tmp/sparse \
    && make \
    && make install PREFIX=/usr \
    && echo "Verifying sparse installation..." \
    && which sparse \
    && sparse --version \
    && echo "Sparse successfully installed" \
    && cd / \
    && rm -rf /tmp/sparse

USER patchwise
