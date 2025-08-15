# Docker Architecture Changes

## Overview
Implemented a 3-stage Docker build process for optimal caching and maintainability.

## Architecture

```
base.dockerfile (system packages, users, basic setup)
    ↓
tool-specific.dockerfile (sparse, dt_check, etc. - tool installations only)
    ↓
kernel.dockerfile (universal kernel setup - single source of truth)
```

## Build Process

### Stage 1: Base Image
- **File**: `base.Dockerfile`
- **Purpose**: System packages, user setup, basic tools
- **Output**: `patchwise-base:latest`
- **Changes**:
  - Added `bc` package (required for kernel builds)
  - Removed all kernel-related operations
  - Kept build directory and Python venv setup

### Stage 2: Tool-Specific Image
- **Files**: `Sparse.Dockerfile`, `DtCheck.Dockerfile`, etc.
- **Purpose**: Install tool-specific dependencies
- **Output**: `patchwise-{tool}-intermediate`
- **Changes**: No kernel operations, just tool installations

### Stage 3: Final Image with Kernel
- **File**: `kernel.Dockerfile` (NEW)
- **Purpose**: Universal kernel setup for any tool
- **Output**: `patchwise-{tool}` (final image)
- **Features**:
  - Accepts any tool image as base via `TOOL_IMAGE` build arg
  - Copies kernel tree with proper ownership
  - Performs git operations (reset, clean)
  - Fixes all file permissions for `patchwise` user

## Benefits

1. **Optimal Caching**: Tool installations cached independently of kernel changes
2. **Single Source of Truth**: Kernel logic only in `kernel.Dockerfile`
3. **DRY Principle**: No duplication of kernel setup across tools
4. **Permission Fix**: Resolves the "Permission denied" touch issues
5. **Missing Package Fix**: Added `bc` package for kernel builds
6. **Faster Builds**: Only kernel layer rebuilds when kernel changes

## Build Flow Example

For sparse analysis:
1. `base.Dockerfile` → `patchwise-base:latest`
2. `Sparse.Dockerfile` → `patchwise-sparse-intermediate`
3. `kernel.Dockerfile` → `patchwise-sparse` (final)

## Files Modified

- ✅ **NEW**: `patchwise/dockerfiles/kernel.Dockerfile`
- ✅ **UPDATED**: `patchwise/dockerfiles/base.Dockerfile` (removed kernel ops, added `bc`)
- ✅ **UPDATED**: `patchwise/docker.py` (3-stage build process)

## Issues Resolved

- ✅ **Permission denied errors**: Kernel files now owned by `patchwise` user
- ✅ **"bc: not found" errors**: Added `bc` package to base image
- ✅ **Poor caching**: Tool layers now cached independently
- ✅ **Code duplication**: Single kernel setup for all tools
