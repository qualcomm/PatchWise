#!/usr/bin/env python3
"""
Test script to verify sparse is properly installed in the Docker container.
"""

import subprocess
import sys

def test_sparse_in_container():
    """Test if sparse is available and working in the patchwise-sparse container."""
    print("Testing sparse in patchwise-sparse container...")
    
    # First, check if we can find a running sparse container
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=patchwise-sparse", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            print("✗ Failed to list Docker containers")
            return False
            
        containers = result.stdout.strip().split('\n')
        containers = [c for c in containers if c.strip()]
        
        if not containers:
            print("ℹ No running patchwise-sparse containers found")
            print("This is normal - containers are created when patchwise runs")
            return test_sparse_in_new_container()
        
        container_name = containers[0]
        print(f"✓ Found running container: {container_name}")
        
        # Test sparse in the running container
        return test_sparse_commands(container_name)
        
    except Exception as e:
        print(f"✗ Error checking containers: {e}")
        return False

def test_sparse_in_new_container():
    """Test sparse by creating a temporary container."""
    print("Testing sparse by creating temporary container...")
    
    try:
        # Test with a temporary container
        result = subprocess.run(
            ["docker", "run", "--rm", "patchwise-sparse", "which", "sparse"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            print(f"✓ Sparse found at: {result.stdout.strip()}")
            
            # Test sparse version
            version_result = subprocess.run(
                ["docker", "run", "--rm", "patchwise-sparse", "sparse", "--version"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if version_result.returncode == 0:
                print(f"✓ Sparse version: {version_result.stdout.strip()}")
                return True
            else:
                print(f"✗ Sparse version check failed: {version_result.stderr}")
                return False
        else:
            print(f"✗ Sparse not found in container: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        print("✗ Container test timed out")
        return False
    except Exception as e:
        print(f"✗ Error testing container: {e}")
        return False

def test_sparse_commands(container_name):
    """Test sparse commands in a specific container."""
    tests = [
        (["which", "sparse"], "Check sparse location"),
        (["sparse", "--version"], "Check sparse version"),
        (["sparse", "--help"], "Check sparse help")
    ]
    
    for cmd, desc in tests:
        try:
            result = subprocess.run(
                ["docker", "exec", container_name] + cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                print(f"✓ {desc}: {result.stdout.strip()[:100]}")
            else:
                print(f"✗ {desc} failed: {result.stderr.strip()}")
                return False
                
        except Exception as e:
            print(f"✗ {desc} error: {e}")
            return False
    
    return True

def main():
    """Run sparse container tests."""
    print("=== Sparse Container Tests ===\n")
    
    if test_sparse_in_container():
        print("\n🎉 Sparse is properly installed in the container!")
        print("The sparse analysis should now work correctly.")
        return 0
    else:
        print("\n❌ Sparse installation issues detected.")
        print("You may need to rebuild the patchwise-sparse Docker image:")
        print("  docker rmi patchwise-sparse")
        print("  # Then run patchwise again to rebuild")
        return 1

if __name__ == "__main__":
    sys.exit(main())
