#!/usr/bin/env python3
import os
import shutil
import sys

def main():
    # Paths are relative to the script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.abspath(os.path.join(script_dir, ".."))
    src_app = os.path.join(root_dir, "app")
    dest_app = os.path.join(root_dir, "functions", "app")

    print(f"Predeploy packaging: Syncing {src_app} to {dest_app}...")

    # Remove existing destination directory if it exists
    if os.path.exists(dest_app):
        print(f"Removing old build at {dest_app}...")
        try:
            shutil.rmtree(dest_app)
        except Exception as e:
            print(f"Warning: Could not remove {dest_app}: {e}")

    # Define ignore pattern for copytree
    ignore_pattern = shutil.ignore_patterns(
        "__pycache__",
        "*.pyc",
        "*.pyo",
        "*.pyd",
        ".pytest_cache",
        "*.db",
        "*.sqlite"
    )

    try:
        shutil.copytree(src_app, dest_app, ignore=ignore_pattern)
        print("Predeploy packaging completed successfully!")
    except Exception as e:
        print(f"Error copying package app to functions/app: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
