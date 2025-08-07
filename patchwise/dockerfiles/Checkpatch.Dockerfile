# Inherit from the base image
FROM patchwise-base:latest

USER root

RUN python3 -m venv /home/patchwise/.venv
ENV PATH="/home/patchwise/.venv/bin:$PATH"

RUN pip3 install codespell

USER patchwise