"""Open applications on the user's laptop (Windows / macOS / Linux)."""
from __future__ import annotations

import platform
import shutil
import subprocess

from . import tool

# nicknames people actually say -> canonical launch key
ALIASES = {
    "visual studio code": "vscode", "vs code": "vscode", "vscode": "vscode",
    "google chrome": "chrome", "chrome": "chrome",
    "file manager": "files", "explorer": "files", "finder": "files",
    "terminal": "terminal", "iterm": "iterm",
    "browser": "chrome", "music": "spotify",
}

# name -> per-OS launch command
_LAUNCH = {
    "chrome":     {"windows": "start chrome", "linux": "google-chrome", "darwin": "open -a 'Google Chrome'"},
    "chromium":   {"linux": "chromium", "darwin": "open -a Chromium"},
    "edge":       {"windows": "start msedge", "linux": "microsoft-edge", "darwin": "open -a 'Microsoft Edge'"},
    "firefox":    {"windows": "start firefox", "linux": "firefox", "darwin": "open -a Firefox"},
    "spotify":    {"windows": "start spotify", "linux": "spotify", "darwin": "open -a Spotify"},
    "youtube":    {"windows": "start https://youtube.com", "linux": "xdg-open https://youtube.com", "darwin": "open https://youtube.com"},
    "google":     {"windows": "start https://google.com", "linux": "xdg-open https://google.com", "darwin": "open https://google.com"},
    "vscode":     {"windows": "code", "linux": "code", "darwin": "open -a 'Visual Studio Code'"},
    "visual studio code": {"windows": "code", "linux": "code", "darwin": "open -a 'Visual Studio Code'"},
    "code":       {"windows": "code", "linux": "code", "darwin": "open -a 'Visual Studio Code'"},
    "terminal":   {"windows": "start wt", "linux": "x-terminal-emulator || gnome-terminal || konsole", "darwin": "open -a Terminal"},
    "cmd":        {"windows": "start cmd"},
    "powershell": {"windows": "start powershell"},
    "iterm":      {"darwin": "open -a iTerm"},
    "files":      {"windows": "explorer", "linux": "nautilus || dolphin || thunar || xdg-open ~", "darwin": "open ~"},
    "explorer":   {"windows": "explorer"},
    "finder":     {"darwin": "open ."},
    "file manager": {"linux": "nautilus || dolphin || thunar"},
    "calculator": {"windows": "start calc", "linux": "gnome-calculator || kcalc", "darwin": "open -a Calculator"},
    "notepad":    {"windows": "start notepad", "darwin": "open -a TextEdit"},
    "word":       {"windows": "start winword"},
    "excel":      {"windows": "start excel"},
    "powerpoint": {"windows": "start powerpnt"},
    "slack":      {"windows": "start slack", "linux": "slack", "darwin": "open -a Slack"},
    "discord":    {"windows": "start discord", "linux": "discord", "darwin": "open -a Discord"},
    "telegram":   {"windows": "start telegram", "linux": "telegram-desktop", "darwin": "open -a Telegram"},
    "whatsapp":   {"windows": "start whatsapp", "linux": "whatsapp-for-linux", "darwin": "open -a WhatsApp"},
    "mail":       {"windows": "start outlook", "darwin": "open -a Mail"},
    "outlook":    {"windows": "start outlook", "darwin": "open -a Outlook"},
    "gmail":      {"windows": "start https://mail.google.com", "linux": "xdg-open https://mail.google.com", "darwin": "open https://mail.google.com"},
    "maps":       {"windows": "start https://maps.google.com", "linux": "xdg-open https://maps.google.com", "darwin": "open https://maps.google.com"},
}


def _spawn(cmd: str, label: str = "that") -> None:
    sysname = platform.system().lower()
    if sysname == "windows" or " || " in cmd:
        subprocess.Popen(cmd, shell=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        parts = cmd.split()
        exe = shutil.which(parts[0])
        if not exe:
            raise RuntimeError(f"{label} doesn't appear to be installed on this machine")
        subprocess.Popen([exe] + parts[1:],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def launch_key_for(name: str) -> str:
    n = name.strip().lower()
    if n in ALIASES:
        return ALIASES[n]
    return n


@tool("open_app", "Open an application on this laptop.",
      {"name": "app name: e.g. chrome, spotify, vscode, files, calculator"})
def open_app(name: str) -> dict:
    name = launch_key_for(name)
    label = name.capitalize()
    cmd = (_LAUNCH.get(name) or {}).get(platform.system().lower())
    if cmd:
        _spawn(cmd, label=label)
        return {"opened": name}
    exe = shutil.which(name) or shutil.which(name.replace(" ", ""))
    if exe:
        _spawn(exe, label=label)
        return {"opened": name}
    raise RuntimeError(
        f"I don't have a launch command for '{name}'. I know: "
        + ", ".join(sorted(k for k in _LAUNCH if " " not in k)) + ".")
