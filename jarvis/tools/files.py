"""Find files on the laptop (fast, depth-bounded)."""
from __future__ import annotations

import fnmatch
import os

from . import tool

_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".cache",
              ".local", ".npm", ".mypy_cache", ".pytest_cache", ".snap", "snap",
              "appdata", "android"}


@tool("find_files", "Find files on this laptop by name pattern.",
      {"pattern": "string: glob pattern, e.g. 'report*' or '*.pdf'",
       "limit": "integer (optional): default 8"})
def find_files(pattern: str, limit: int = 8, search_dir: str | None = None) -> dict:
    root = os.path.expanduser(search_dir or "~")
    found: list = []
    if not os.path.isdir(root):
        return {"found": found}
    root_depth = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d.lower() not in _SKIP_DIRS and not d.startswith(".")]
        if dirpath.count(os.sep) - root_depth > 4:
            dirnames[:] = []
            continue
        for fn in filenames:
            if fnmatch.fnmatch(fn.lower(), pattern.lower()):
                found.append(os.path.join(dirpath, fn))
                if len(found) >= limit:
                    return {"found": found}
    return {"found": found}
