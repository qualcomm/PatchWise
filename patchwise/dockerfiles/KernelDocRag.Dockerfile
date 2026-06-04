# Inherit from the base image
FROM patchwise-base:latest

USER root

RUN pip3 install chromadb

USER patchwise

