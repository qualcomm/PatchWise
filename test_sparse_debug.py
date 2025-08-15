#!/usr/bin/env python3
"""
Test script to help debug sparse issues by checking if sparse is available
and can run basic commands.
"""

import subprocess
import sys
from pathlib import Path

def test_sparse_availability():
    """Test if sparse is available in the system."""
    print("Testing sparse availability...")
    
    try:
        result = subprocess.run(
            ["sparse", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            print(f"✓ Sparse is available: {result.stdout.strip()}")
            return True
        else:
            print(f"✗ Sparse command failed: {result.stderr}")
            return False
    except FileNotFoundError:
        print("✗ Sparse not found in PATH")
        return False
    except subprocess.TimeoutExpired:
        print("✗ Sparse command timed out")
        return False
    except Exception as e:
        print(f"✗ Error running sparse: {e}")
        return False

def test_docker_sparse():
    """Test if sparse is available in the Docker container."""
    print("Testing sparse in Docker container...")
    
    try:
        # Check if we can run a simple docker command
        result = subprocess.run(
            ["docker", "run", "--rm", "patchwise-base:latest", "which", "sparse"],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            print(f"✓ Sparse found in container: {result.stdout.strip()}")
            return True
        else:
            print(f"✗ Sparse not found in container: {result.stderr}")
            return False
    except FileNotFoundError:
        print("✗ Docker not found")
        return False
    except subprocess.TimeoutExpired:
        print("✗ Docker command timed out")
        return False
    except Exception as e:
        print(f"✗ Error testing Docker sparse: {e}")
        return False

def check_sparse_dockerfile():
    """Check if sparse is installed in the Dockerfile."""
    print("Checking Dockerfile for sparse installation...")
    
    dockerfile_path = Path("patchwise/dockerfiles/base.Dockerfile")
    if not dockerfile_path.exists():
        print("✗ base.Dockerfile not found")
        return False
    
    with open(dockerfile_path, 'r') as f:
        content = f.read()
    
    if "sparse" in content.lower():
        print("✓ Sparse mentioned in Dockerfile")
        return True
    else:
        print("✗ Sparse not found in Dockerfile - this might be the issue!")
        print("Sparse needs to be installed in the Docker container")
        return False

def main():
    """Run all sparse tests."""
    print("=== Sparse Debug Tests ===\n")
    
    tests = [
        ("Host Sparse Availability", test_sparse_availability),
        ("Dockerfile Sparse Check", check_sparse_dockerfile),
        ("Docker Container Sparse", test_docker_sparse),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n--- {test_name} ---")
        if test_func():
            passed += 1
        print()
    
    print("=== Results ===")
    print(f"Passed: {passed}/{total}")
    
    if passed < total:
        print("\n=== Recommendations ===")
        print("If sparse is not available in the Docker container, you need to:")
        print("1. Add 'sparse' to the package installation in base.Dockerfile")
        print("2. Rebuild the Docker image")
        print("3. Test again")
    
    return 0 if passed == total else 1

if __name__ == "__main__":
    sys.exit(main())
