"""Files the plugin keeps at stable paths in its data dir.

The plugin's own directory changes with every version, so a `statusLine`
setting or a CLAUDE.md import cannot point into it. `setup` writes a launcher
and a copy of the compact rules into the data dir, which survives updates;
each session start refreshes them, but only once `setup` has created them.
"""

from __future__ import annotations

from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
ENTRY = PLUGIN_ROOT / "scripts" / "context_optimization.py"
RULES = PLUGIN_ROOT / "rules.md"

LAUNCHER = """\
#!/usr/bin/env python3
# Written by varis-context-optimization; refreshed at each session start.
# Runs the statusline of the installed plugin version.
import os, runpy, sys
os.environ.setdefault("CLAUDE_PLUGIN_DATA", {data!r})
sys.argv = [sys.argv[0], "statusline"]
runpy.run_path({entry!r}, run_name="__main__")
"""


def launcher_path(data: Path) -> Path:
    return data / "statusline.py"


def rules_path(data: Path) -> Path:
    return data / "rules.md"


def install(data: Path) -> None:
    data.mkdir(parents=True, exist_ok=True)
    _write_if_changed(launcher_path(data), LAUNCHER.format(data=str(data), entry=str(ENTRY)))
    _write_if_changed(rules_path(data), RULES.read_text(encoding="utf-8"))


def refresh(data: Path) -> None:
    if launcher_path(data).exists() or rules_path(data).exists():
        install(data)


def _write_if_changed(path: Path, text: str) -> None:
    try:
        if path.read_text(encoding="utf-8") == text:
            return
    except FileNotFoundError:
        pass
    path.write_text(text, encoding="utf-8")
