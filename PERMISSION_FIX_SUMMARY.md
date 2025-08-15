# Permission Fix Summary

## Problem
The shared Docker volume approach was still causing permission errors because:
1. Host creates commit-specific build directories with host user permissions
2. Docker container's `patchwise` user cannot write to these directories
3. Error: `PermissionError: [Errno 13] Permission denied: '/tmp/patchwise/sandbox/build/{commit_sha}/build.log'`

## Root Cause
- Shared volume `/tmp/patchwise/sandbox/build/` was initialized with proper permissions
- But individual commit subdirectories (e.g., `/tmp/patchwise/sandbox/build/96675e9770027026f661cf0af2b5c9cbac8bdfd4/`) were created by host with host permissions
- Container's `patchwise` user couldn't write to these subdirectories

## Solution Implemented

### 1. Enhanced DockerManager
- **Added `commit_sha` parameter** to DockerManager constructor
- **Added `_fix_build_directory_permissions()` method** that:
  - Creates commit-specific directory inside container as root
  - Sets proper ownership (`patchwise:patchwise`)
  - Sets proper permissions (755)

### 2. Updated Container Startup
- **Modified `start_container_with_shared_volume()`** to call permission fix after container starts
- **Automatic permission fixing** for each commit's build directory

### 3. Updated PatchReview Integration
- **Pass commit SHA** to DockerManager constructor
- **Seamless integration** with existing workflow

## Technical Details

### Permission Fix Process
```bash
# Inside container, as root:
mkdir -p /shared/build/{commit_sha}
chown -R patchwise:patchwise /shared/build/{commit_sha}
chmod -R 755 /shared/build/{commit_sha}
```

### Flow
1. Container starts with shared volume mounted
2. `_fix_build_directory_permissions()` runs automatically
3. Commit-specific directory created with proper permissions
4. `patchwise` user can now write build.log and other files

## Files Modified
- ✅ `patchwise/docker.py` - Added commit_sha parameter and permission fixing
- ✅ `patchwise/patch_review/patch_review.py` - Pass commit_sha to DockerManager

## Expected Result
- ✅ No more "Permission denied" errors when writing to build directories
- ✅ Each commit gets its own properly-permissioned build directory
- ✅ Shared volume caching still works optimally
- ✅ Container isolation maintained (no host user ID mapping needed)

## Testing
Run patchwise again on a patch - the permission error should be resolved and build.log should be created successfully.
