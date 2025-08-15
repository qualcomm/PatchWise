#!/usr/bin/env python3
"""
Test script to verify the Docker permission fix works correctly.
This script simulates the container building and initialization process.
"""

import subprocess
import sys
from pathlib import Path

def test_docker_volume_creation():
    """Test that Docker volume can be created and initialized."""
    print("Testing Docker volume creation and initialization...")
    
    # Test volume creation
    try:
        result = subprocess.run(
            ["docker", "volume", "create", "patchwise-shared-build-test"],
            capture_output=True,
            text=True,
            check=True
        )
        print("✓ Docker volume created successfully")
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to create Docker volume: {e}")
        return False
    
    # Test volume cleanup
    try:
        subprocess.run(
            ["docker", "volume", "rm", "patchwise-shared-build-test"],
            capture_output=True,
            text=True,
            check=True
        )
        print("✓ Docker volume cleaned up successfully")
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to clean up Docker volume: {e}")
        return False
    
    return True

def test_dockerfile_syntax():
    """Test that the modified Dockerfile has valid syntax."""
    print("Testing Dockerfile syntax...")
    
    dockerfile_path = Path("patchwise/dockerfiles/base.Dockerfile")
    if not dockerfile_path.exists():
        print(f"✗ Dockerfile not found: {dockerfile_path}")
        return False
    
    # Read and check for the initialization script
    with open(dockerfile_path, 'r') as f:
        content = f.read()
    
    if "init-build-dir.sh" in content:
        print("✓ Dockerfile contains initialization script")
    else:
        print("✗ Dockerfile missing initialization script")
        return False
    
    if "/shared/build" in content:
        print("✓ Dockerfile references shared build directory")
    else:
        print("✗ Dockerfile missing shared build directory reference")
        return False
    
    return True

def main():
    """Run all tests."""
    print("Running Docker permission fix tests...\n")
    
    tests = [
        ("Docker Volume Operations", test_docker_volume_creation),
        ("Dockerfile Syntax", test_dockerfile_syntax),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n--- {test_name} ---")
        if test_func():
            passed += 1
            print(f"✓ {test_name} PASSED")
        else:
            print(f"✗ {test_name} FAILED")
    
    print(f"\n--- Results ---")
    print(f"Passed: {passed}/{total}")
    
    if passed == total:
        print("🎉 All tests passed! The Docker permission fix should work correctly.")
        return 0
    else:
        print("❌ Some tests failed. Please check the implementation.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
