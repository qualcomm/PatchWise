# Inherit from the base image
FROM patchwise-base:latest

USER root

# RUN chown -R patchwise:patchwise /home/patchwise/build

# RUN wget https://apt.llvm.org/llvm.sh && \
#     chmod +x llvm.sh && \
#     ./llvm.sh 14 && \
#     rm llvm.sh

RUN apt-get update && apt-get install -y --no-install-recommends \
    swig \
    meson \
    && rm -rf /var/lib/apt/lists/*

RUN git clone git://git.kernel.org/pub/scm/utils/dtc/dtc.git /home/patchwise/dtc \
    && cd /home/patchwise/dtc \
    && meson setup builddir/ \
    && meson compile -C builddir/ \
    && meson install -C builddir/ \
    && cd /home/patchwise \
    && rm -rf /home/patchwise/dtc

RUN pip3 install dtschema
RUN pip3 install yamllint

USER patchwise
