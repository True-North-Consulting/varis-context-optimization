"""`setup`: what a plugin cannot set for itself.

A plugin's settings may not set the compaction window, the status line or a
permission rule, and a compaction ignores rules a hook injects (only CLAUDE.md
is read for them). So `setup` writes the stable launcher and rules copy into
the data dir and prints, with a check of each, the lines for the user to add.
It never edits a settings file or CLAUDE.md itself.
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Optional

from . import files
from .settings import compact_window, compaction_point, config_dir

RECOMMENDED_WINDOW = 300_000


def setup(data: Path, project_dir: Optional[str]) -> str:
    files.install(data)
    user_dir = config_dir()
    settings_file = user_dir / "settings.json"
    user_settings = _json(settings_file)
    launcher = files.launcher_path(data)
    rules = files.rules_path(data)
    allow_rules = [f"{tool}({_tilde(data)}/ledgers/**)" for tool in ("Read", "Edit")]
    window = compact_window(project_dir)
    status_command = ((user_settings.get("statusLine") or {}).get("command") or "")
    allowed = (user_settings.get("permissions") or {}).get("allow") or []
    claude_md = user_dir / "CLAUDE.md"
    imported = claude_md.exists() and _mentions(claude_md.read_text(encoding="utf-8"), rules)

    snippet = {
        "autoCompactWindow": window or RECOMMENDED_WINDOW,
        "statusLine": {"type": "command", "command": f"sh {shlex.quote(str(launcher))}"},
        "permissions": {"allow": allow_rules},
    }
    checks = [
        _check(window is not None,
               f"compaction window: {window:,} tokens (compacts at about {compaction_point(window):,})"
               if window else "compaction window: not set — the model's default applies (about 967k on 1M models)"),
        _check(str(launcher) in status_command, "status line: " + (
            "this plugin's launcher" if str(launcher) in status_command else "not this plugin's")),
        _check(all(any(_mentions(rule, data) and rule.startswith(tool) for rule in allowed)
                   for tool in ("Read(", "Edit(")),
               "ledger reads and writes allowed without a prompt"),
        _check(imported, f"compact rules imported in {_tilde(claude_md)}"),
    ]
    return "\n".join([
        "Varis Context Optimization — setup",
        "",
        *checks,
        "",
        f"Add to {_tilde(settings_file)} (merge with the keys already there):",
        json.dumps(snippet, indent=2),
        "",
        f"Add this line to {_tilde(claude_md)}:",
        f"@{_tilde(rules)}",
        "",
        f"The window is a trade-off: smaller is cheaper per turn, larger compacts less often. "
        f"{RECOMMENDED_WINDOW:,} halved the cost per turn in the author's sessions. "
        "Settings apply to sessions started afterwards.",
    ])


def _check(ok: bool, text: str) -> str:
    return f"{'✔' if ok else '✘'} {text}"


def _json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    return value if isinstance(value, dict) else {}


def _mentions(text: str, path: Path) -> bool:
    """Whether `text` names `path`, written out or with `~`."""
    return str(path) in text or _tilde(path) in text


def _tilde(path: Path) -> str:
    try:
        return "~/" + path.relative_to(Path.home()).as_posix()
    except ValueError:
        return str(path)
