# Inherit from the base image
FROM patchwise-base:latest

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    ripgrep \
    perl \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install "tree-sitter>=0.24" "tree-sitter-c>=0.23"

# Tree-sitter kernel indexer is invoked by AiCodeReview as `python3 ts_indexer.py`,
# so it must be world-readable. Pin the mode explicitly: BuildKit preserves the
# source file's mode through COPY (the classic builder normalized it to 0644), so
# a restrictive umask on the build host would otherwise leave it unreadable.
COPY --chmod=0755 patch_review/ai_review/ts_indexer.py /home/patchwise/bin/ts_indexer.py

USER patchwise
