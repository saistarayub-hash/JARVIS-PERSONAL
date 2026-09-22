# JARVIS v16 Standalone Executable Release Pipeline

This release pipeline automates standalone single-file binary builds for JARVIS across Linux, Windows, and macOS.

## Components

1. **PyInstaller Specification (`jarvis.spec`)**
   - Bundles all UI static assets (`jarvis/ui/*`) and configuration templates (`config.example.yaml`).
   - Includes uvicorn ASGI hidden imports and sqlite3 dependencies.

2. **Standalone Build Script (`scripts/build_standalone.py`)**
   - Handles cross-platform binary invocation and platform-specific asset naming (`jarvis-linux-x86_64`, `jarvis-windows-amd64.exe`, `jarvis-macos-x86_64`).

3. **GitHub Actions Workflow (`.github/workflows/release.yml`)**
   - Triggered on tag push `v*` (e.g. `v1.0.0`).
   - Matrix build on `ubuntu-latest`, `windows-latest`, and `macos-latest`.
   - Uploads compiled binaries directly to GitHub Releases.

4. **Testing Suite (`tests/test_standalone.py`)**
   - Validates `.spec` configuration, asset path existence, and platform asset naming.
