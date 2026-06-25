# Inherit from the base image
FROM patchwise-base:latest

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    ripgrep \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install "tree-sitter>=0.24" "tree-sitter-c>=0.23"

# Tree-sitter kernel indexer — required by the worker's find_definition /
# find_callers / find_callees navigation tools (same stack as AiCodeReview).
COPY patch_review/ai_review/ts_indexer.py /home/patchwise/bin/ts_indexer.py
RUN chmod +x /home/patchwise/bin/ts_indexer.py

USER patchwise
