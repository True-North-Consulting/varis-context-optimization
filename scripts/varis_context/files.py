"""Files the plugin keeps at stable paths in its data dir.

The plugin's own directory changes with every version, so a `statusLine`
setting or a CLAUDE.md import cannot point into it. Each session start writes
a status-line launcher and a copy of the compact rules into the data dir,
which survives updates, so settings can point there before `setup` ever ran.
Paths use forward slashes: Git Bash and Python on Windows both take them.
"""

from __future__ import annotations

import shlex
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
RUN = PLUGIN_ROOT / "scripts" / "run.sh"
RULES = PLUGIN_ROOT / "rules.md"

LAUNCHER = """\
#!/bin/sh
# Written by varis-context-optimization; refreshed at each session start.
# Runs the status line of the installed plugin version.
CLAUDE_PLUGIN_DATA=${{CLAUDE_PLUGIN_DATA:-{data}}}
export CLAUDE_PLUGIN_DATA
exec sh {run} statusline
"""


def command(*args: object) -> str:
    """A shell command line running the plugin; it works in Git Bash too."""
    return " ".join(["sh", shlex.quote(RUN.as_posix())] + [shlex.quote(str(a)) for a in args])


def launcher_path(data: Path) -> Path:
    return data / "statusline.sh"


def rules_path(data: Path) -> Path:
    return data / "rules.md"


def install(data: Path) -> None:
    data.mkdir(parents=True, exist_ok=True)
    _write_if_changed(launcher_path(data), LAUNCHER.format(data=shlex.quote(data.as_posix()), run=shlex.quote(RUN.as_posix())))
    _write_if_changed(rules_path(data), RULES.read_text(encoding="utf-8"))


def _write_if_changed(path: Path, text: str) -> None:
    try:
        if path.read_text(encoding="utf-8") == text:
            return
    except FileNotFoundError:
        pass
    path.write_text(text, encoding="utf-8")
