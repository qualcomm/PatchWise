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
    && rm -rf /var/lib/apt/lists/*

RUN git clone git://git.kernel.org/pub/scm/utils/dtc/dtc.git /home/patchwise/dtc \
    && cd /home/patchwise/dtc \
    && make \
    && make install \
    && cd /home/patchwise \
    && rm -rf /home/patchwise/dtc

# Install dtschema
# RUN pip3 install --upgrade dtschema --break-system-packages
RUN python3 -m venv /home/patchwise/.venv
ENV PATH="/home/patchwise/.venv/bin:$PATH"

# RUN pip3 install --upgrade dtschema
# RUN pip3 install git+https://github.com/devicetree-org/dt-schema.git@master
RUN pip3 install "pylibfdt<1.7.1"
RUN pip3 install dtschema
RUN pip3 install yamllint

# RUN git clone https://github.com/devicetree-org/pylibfdt.git /home/patchwise/pylibfdt \
#     && cd /home/patchwise/pylibfdt \
#     && ./setup.py install \
#     && cd /home/patchwise \
#     && rm -rf /home/patchwise/pylibfdt

# RUN chown -R patchwise:patchwise /home/patchwise/kernel
# RUN chown -R patchwise:patchwise /home/patchwise/build

USER patchwise
