# Inherit from the base image
FROM patchwise-base:latest

USER root

# DtbsCheck doesn't need additional packages beyond what's in base
# All required tools (make, dtc, etc.) are already available in base image

USER patchwise
