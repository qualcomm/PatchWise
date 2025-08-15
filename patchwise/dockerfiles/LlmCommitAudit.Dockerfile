# Inherit from the base image
FROM patchwise-base:latest

USER root

# LlmCommitAudit is a simple AI review that doesn't need additional packages
# All required tools (python3, git, etc.) are already available in base image

USER patchwise
