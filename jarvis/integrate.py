"""v10 integration: make JARVIS part of the machine, not an app you open.

Real artifacts, written to real paths — then real service calls
(systemctl / launchctl / Termux boot). Every step reports honestly: if this
machine refuses a service (no user systemd in a container, e.g.), you get
"failed: ..." in the report, never a silently-skipped checkbox.

Installables
  linux   ~/.config/systemd/user/jarvis.service  (+ enable, --now)
  linux   ~/.config/autostart/jarvis.desktop     (GUI-session fallback)
  macos   ~/Library/LaunchAgents/ai.jarvis.core.plist (+ launchctl load)
  windows %APPDATA%\\...\\Startup\\jarvis-core.bat
  termux  ~/.termux/boot/jarvis-agent.sh         (phone agent survives reboot)
  all     ~/.local/bin/jarvis                    (the command, from any shell)
  all     PATH line in .bashrc/.zshrc between markers (idempotent)
"""
from __future__ import annotations

import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MARK = ">>> jarvis integration >>>"
END = "<<< jarvis integration <<<"


def detect_os() -> str:
    if os.environ.get("TERMUX_VERSION") or "com.termux" in os.environ.get(
            "PREFIX", ""):
        return "termux"
    p = platform.system().lower()
    return {"linux": "linux", "darwin": "macos",
            "windows": "windows"}.get(p, p or "unknown")


def _root_and_python(root: Optional[str]) -> Tuple[str, str]:
    root = str(Path(root or os.getcwd()).resolve())
    py = sys.executable or shutil.which("python3") or "python3"
    return root, py


# ------------------------------------------------------------- file contents
def systemd_unit(root: str, py: str, port: int) -> str:
    return f"""[Unit]
Description=JARVIS personal core
After=network-online.target

[Service]
WorkingDirectory={root}
ExecStart={py} -u run.py --port {port} --headless
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""


def autostart_desktop(root: str, py: str, port: int) -> str:
    return f"""[Desktop Entry]
Type=Application
Name=JARVIS core
Exec={py} {root}/run.py --port {port} --headless
X-GNOME-Autostart-enabled=true
Terminal=false
"""


def launchd_plist(root: str, py: str, port: int) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>ai.jarvis.core</string>
  <key>ProgramArguments</key><array>
    <string>{py}</string><string>-u</string><string>run.py</string>
    <string>--port</string><string>{port}</string><string>--headless</string>
  </array>
  <key>WorkingDirectory</key><string>{root}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>StandardOutPath</key><string>{root}/data/jarvis.log</string>
  <key>StandardErrorPath</key><string>{root}/data/jarvis.err</string>
</dict></plist>
"""


def windows_startup_bat(root: str, py: str, port: int) -> str:
    return f"""@echo off
rem JARVIS core autostart (installed by jarvis.cli)
cd /d "{root}"
start "" /min "{py}" run.py --port {port} --headless
"""


def termux_boot_script(root: str, py: str, core_url: str, name: str,
                      token: str) -> str:
    return f"""#!/data/data/com.termux/files/usr/bin/bash
# JARVIS phone agent — starts with Termux:Boot, keeps the fleet link alive.
termux-wake-lock
cd {root}
nohup {py} -m jarvis.fleet.agent --name {name} --url {core_url} \\
    --token {token} >> "$HOME/jarvis-agent.log" 2>&1 &
"""


def shell_shim(root: str, py: str, port: int) -> str:
    return f"""#!/usr/bin/env {py}
""" + f'''# JARVIS shell entry point (installed by jarvis.cli)
import sys
sys.path.insert(0, {root!r})
from jarvis.cli import main
raise SystemExit(main())
'''


def rc_snippet(local_bin: str) -> str:
    return (f"# {MARK}\n"
            f'case ":$PATH:" in *":{local_bin}:"*) ;;\n'
            f'*) export PATH="{local_bin}:$PATH" ;;\n'
            f"# {END}\n")


# ---------------------------------------------------------------- installer
class Integrator:
    def __init__(self, root: Optional[str] = None, port: int = 8595,
                 os_name: Optional[str] = None, home: Optional[str] = None,
                 core_url: str = "", agent_name: str = "phone"):
        self.root, self.py = _root_and_python(root)
        self.port = int(port)
        self.os = os_name or detect_os()
        self.home = Path(home or os.path.expanduser("~"))
        self.core_url = core_url or f"ws://{os.environ.get('JARVIS_CORE', '127.0.0.1')}:{self.port}"
        self.agent_name = agent_name

    # -- planned files ------------------------------------------------------
    def plan(self) -> List[Tuple[str, str, bool]]:
        """[(abs path, contents, executable?)] for this OS."""
        files: List[Tuple[str, str, bool]] = []
        local_bin = self.home / ".local" / "bin"
        files.append((str(local_bin / "jarvis"),
                      shell_shim(self.root, self.py, self.port), True))
        if self.os == "linux":
            files.append((str(self.home / ".config/systemd/user/jarvis.service"),
                          systemd_unit(self.root, self.py, self.port), False))
            files.append((str(self.home / ".config/autostart/jarvis.desktop"),
                          autostart_desktop(self.root, self.py, self.port),
                          False))
        elif self.os == "macos":
            files.append((str(self.home / "Library/LaunchAgents/ai.jarvis.core.plist"),
                          launchd_plist(self.root, self.py, self.port), False))
        elif self.os == "windows":
            startup = Path(os.environ.get("APPDATA", str(self.home))) / (
                "Microsoft/Windows/Start Menu/Programs/Startup")
            files.append((str(startup / "jarvis-core.bat"),
                          windows_startup_bat(self.root, self.py, self.port),
                          False))
        elif self.os == "termux":
            token = os.environ.get("JARVIS_TOKEN", "")
            files.append((str(self.home / ".termux/boot/jarvis-agent.sh"),
                          termux_boot_script(self.root, self.py, self.core_url,
                                             self.agent_name, token), True))
        return files

    def _rc_targets(self) -> List[Path]:
        if self.os == "termux":
            return [self.home / ".bashrc"]
        return [self.home / ".bashrc", self.home / ".zshrc"]

    # -- actions ------------------------------------------------------------
    def install(self, dry: bool = False) -> Dict[str, Any]:
        report: Dict[str, Any] = {"os": self.os, "files": [], "commands": [],
                                  "rc": [], "dry_run": dry}
        local_bin = self.home / ".local" / "bin"
        for path, contents, exe in self.plan():
            report["files"].append(path)
            if dry:
                continue
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            if not dry and p.exists() and p.read_text() == contents:
                pass  # idempotent: already perfect
            else:
                p.write_text(contents)
            if exe:
                p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP |
                        stat.S_IXOTH)
        if not dry:
            for rc in self._rc_targets():
                if not rc.exists():
                    continue  # never create rc files from scratch — only join
                text = rc.read_text()
                if MARK in text:
                    report["rc"].append(f"{rc}: already integrated")
                    continue
                if rc.parent.is_dir():
                    with open(rc, "a") as fh:
                        fh.write("\n" + rc_snippet(str(local_bin)) + "\n")
                    report["rc"].append(f"{rc}: PATH line added")
        # service enablement — real commands, honest results
        cmds = self._enable_cmds()
        for c in cmds:
            report["commands"].append(c)
            if dry:
                continue
            try:
                r = subprocess.run(c, shell=True, capture_output=True,
                                   text=True, timeout=20)
                if r.returncode != 0:
                    report.setdefault("warnings", []).append(
                        f"`{c}` failed: {(r.stderr or r.stdout).strip()[:180]}")
            except Exception as exc:  # noqa: BLE001 — never crash the install
                report.setdefault("warnings", []).append(
                    f"`{c}` failed: {exc.__class__.__name__}")
        return report

    def _enable_cmds(self) -> List[str]:
        if self.os == "linux":
            return ["systemctl --user daemon-reload",
                    "systemctl --user enable --now jarvis.service"]
        if self.os == "macos":
            return [f"launchctl unload ~/Library/LaunchAgents/ai.jarvis.core.plist "
                    f"2>/dev/null; launchctl load ~/Library/LaunchAgents/"
                    f"ai.jarvis.core.plist"]
        if self.os == "termux":
            return ["termux-wake-unlock 2>/dev/null || true"]
        return []

    def uninstall(self) -> Dict[str, Any]:
        rep: Dict[str, Any] = {"os": self.os, "removed": [], "rc": []}
        if self.os == "linux":
            for c in ("systemctl --user disable --now jarvis.service",
                      "systemctl --user daemon-reload"):
                try:
                    subprocess.run(c, shell=True, capture_output=True, timeout=15)
                except Exception:  # noqa: BLE001
                    pass
        for path, _, _ in self.plan():
            p = Path(path)
            if p.exists():
                p.unlink()
                rep["removed"].append(path)
        for rc in self._rc_targets():
            if not rc.exists():
                continue
            text = rc.read_text()
            if MARK not in text:
                continue
            lines, skip = [], False
            for ln in text.splitlines():
                if MARK in ln:
                    skip = True
                    continue
                if END in ln:
                    skip = False
                    continue
                if not skip:
                    lines.append(ln)
            rc.write_text("\n".join(lines) + "\n")
            rep["rc"].append(f"{rc}: marker block removed")
        return rep

    def status(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"os": self.os, "root": self.root,
                               "port": self.port, "files": {}}
        for path, _, _ in self.plan():
            p = Path(path)
            out["files"][path] = ("installed" if p.exists() else "absent")
        if self.os == "linux":
            try:
                r = subprocess.run("systemctl --user is-enabled jarvis.service",
                                   shell=True, capture_output=True, text=True,
                                   timeout=10)
                out["service"] = (r.stdout or r.stderr).strip() or "unknown"
            except Exception as exc:  # noqa: BLE001
                out["service"] = f"unverifiable ({exc.__class__.__name__})"
        else:
            out["service"] = "see platform notes (launchctl / startup folder)"
        return out


def report_text(rep: Dict[str, Any]) -> str:
    lines = [f"Integration for {rep.get('os')}"
             + (f" ({rep.get('root')})" if rep.get("root") else "") + ":"]
    for f in rep.get("files", []):
        lines.append(f"  file: {f}")
    for r in rep.get("rc", []):
        lines.append(f"  shell: {r}")
    for c in rep.get("commands", []):
        lines.append(f"  run: {c}")
    for w in rep.get("warnings", []):
        lines.append(f"  ⚠ {w}")
    if rep.get("dry_run"):
        lines.append("  (dry run — nothing was written)")
    return "\n".join(lines)
