#!/usr/bin/env python3
"""Build standalone executable for JARVIS using PyInstaller.

Usage:
    python scripts/build_standalone.py [--output-name NAME]
"""
from __future__ import annotations

import argparse
import os
import platform
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

    sep = ";" if platform.system().lower() == "windows" else ":"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name", name,
        "--add-data", f"jarvis/ui{sep}jarvis/ui",
        "--add-data", f"config.example.yaml{sep}.",
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols",
        "--hidden-import", "uvicorn.protocols.http",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespan",
        "--hidden-import", "uvicorn.lifespan.on",
        "--hidden-import", "engineio.async_drivers.asgi",
        "run.py"
    ]

    print("Running command:", " ".join(cmd))
    res = subprocess.run(cmd)
    if res.returncode != 0:
        print("PyInstaller build failed!", file=sys.stderr)
        return res.returncode

    dist_dir = os.path.join(os.getcwd(), "dist")
    built_path = os.path.join(dist_dir, name)
    if not os.path.exists(built_path) and platform.system().lower() == "windows" and not name.endswith(".exe"):
        built_path_exe = built_path + ".exe"
        if os.path.exists(built_path_exe):
            built_path = built_path_exe

    print(f"Build succeeded! Binary located at: {built_path}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Build standalone JARVIS binary")
    ap.add_argument("--output-name", default=None, help="Output binary name")
    args = ap.parse_args()
    sys.exit(build(args.output_name))


if __name__ == "__main__":
    main()
