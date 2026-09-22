#!/usr/bin/env python3
"""Build standalone executable for JARVIS using PyInstaller.

Usage:
    python scripts/build_standalone.py [--output-name NAME]
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys


def default_asset_name() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "linux":
        return f"jarvis-linux-{machine}"
    elif system == "windows":
        return f"jarvis-windows-{machine}.exe"
    elif system == "darwin":
        return f"jarvis-macos-{machine}"
    return f"jarvis-{system}-{machine}"


def build(output_name: str | None = None) -> int:
    name = output_name or default_asset_name()
    print(f"Building standalone JARVIS executable: {name}")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name", name,
        "jarvis.spec"
    ]

    res = subprocess.run(cmd)
    if res.returncode != 0:
        print("PyInstaller build failed!", file=sys.stderr)
        return res.returncode

    dist_dir = os.path.join(os.getcwd(), "dist")
    built_path = os.path.join(dist_dir, name)
    if not os.path.exists(built_path) and os.path.exists(os.path.join(dist_dir, "jarvis")):
        shutil.move(os.path.join(dist_dir, "jarvis"), built_path)

    print(f"Build succeeded! Binary located at: {built_path}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Build standalone JARVIS binary")
    ap.add_argument("--output-name", default=None, help="Output binary name")
    args = ap.parse_args()
    sys.exit(build(args.output_name))


if __name__ == "__main__":
    main()
