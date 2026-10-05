"""The auto-compaction window as Claude Code resolves it, and where it fires."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from . import HookError

# Claude Code compacts before the window fills: a 1M window compacts at about
# 967k (documented), a 300k window at about 267k (measured over 17 compactions).
COMPACT_RESERVE = 33_000
# The ledger warning comes this far before the compaction point, or a quarter
# of the point on a small window: one turn can add 10k or more of context.
WARN_MARGIN = 40_000
# Below this share of the compaction point the warning re-arms: a compaction
# has happened since it was given.
REARM_BELOW = 0.5

MANAGED_SETTINGS = (
    Path("/Library/Application Support/ClaudeCode/managed-settings.json"),
    Path("/etc/claude-code/managed-settings.json"),
)


def config_dir() -> Path:
    """Claude Code's user directory: `CLAUDE_CONFIG_DIR`, or `~/.claude`."""
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def compact_window(project_dir: Optional[str], model: Optional[str] = None) -> Optional[int]:
    """The auto-compaction window in tokens; None when nothing sets one.

    The env var wins, then the settings files from managed to user. Within one
    file a window set for the model in `modelSettings` (what `/autocompact`
    writes) wins over the plain `autoCompactWindow`. The `--autocompact` launch
    flag is invisible to a hook.
    """
    env = os.environ.get("CLAUDE_CODE_AUTO_COMPACT_WINDOW")
    if env:
        return _window_value(env, "CLAUDE_CODE_AUTO_COMPACT_WINDOW")
    files = list(MANAGED_SETTINGS)
    if project_dir:
        files += [
            Path(project_dir, ".claude", "settings.local.json"),
            Path(project_dir, ".claude", "settings.json"),
        ]
    files.append(config_dir() / "settings.json")
    for path in files:
        settings = _load(path)
        if settings is None:
            continue
        per_model = _model_settings(settings, model, path).get("autoCompactWindow")
        if per_model is not None:
            return _window_value(per_model, f"modelSettings in {path}")
        if "autoCompactWindow" in settings:
            return _window_value(settings["autoCompactWindow"], str(path))
    return None


def compaction_point(window: int) -> int:
    """The context size at which Claude Code compacts, for a given window."""
    return window - COMPACT_RESERVE


def warn_point(point: int) -> int:
    return point - min(WARN_MARGIN, point // 4)


def _load(path: Path) -> Optional[dict]:
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except PermissionError:
        return None  # a managed-settings file this user may not read
    except ValueError as error:
        raise HookError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(settings, dict):
        raise HookError(f"{path} is not a JSON object")
    return settings


def _model_settings(settings: dict, model: Optional[str], path: Path) -> dict:
    if not model:
        return {}
    by_model = settings.get("modelSettings") or {}
    if not isinstance(by_model, dict):
        raise HookError(f"modelSettings in {path} is not an object")
    wanted = _bare(model)
    for key, value in by_model.items():
        if _bare(key) == wanted and isinstance(value, dict):
            return value
    return {}


def _bare(model: str) -> str:
    """A model id without the context-size suffix: `claude-x[1m]` is `claude-x`."""
    return model.split("[", 1)[0].strip().lower()


def _window_value(value: object, source: str) -> int:
    if isinstance(value, bool):
        raise HookError(f"autoCompactWindow in {source} is not a token count: {value!r}")
    try:
        tokens = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError) as error:
        raise HookError(f"autoCompactWindow in {source} is not a token count: {value!r}") from error
    if tokens <= COMPACT_RESERVE:
        raise HookError(f"autoCompactWindow in {source} is too small: {tokens}")
    return tokens
