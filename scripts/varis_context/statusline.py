"""statusLine command: the context against the compaction point, then the session."""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

from . import PLUGIN_NAME
from .ledger import age_text, checked
from .settings import REARM_BELOW, compact_window, config_dir, compaction_point, warn_point
from .transcript import usage_tokens

GREEN, YELLOW, RED, DIM, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m"
ANSI = re.compile(r"\033\[[0-9;]*m")
SEPARATOR = f"{DIM} · {RESET}"
# Below this terminal width the bar shrinks, so the numbers next to it fit.
WIDE = 100
# A cache about to go cold is worth a glance: the next turn then re-caches it all.
CACHE_SOON = 10 * 60


def statusline(data: dict, now: Optional[float] = None) -> str:
    """Two rows: the context against the compaction point, then the session.

    Each row drops its least important parts from the end until it fits the
    terminal (`COLUMNS`).
    """
    now = time.time() if now is None else now
    columns = int(os.environ.get("COLUMNS") or 0) or None
    return "\n".join((_context_row(data, now, columns), _session_row(data, now, columns)))


def _context_row(data: dict, now: float, columns: Optional[int]) -> str:
    workspace = data.get("workspace") or {}
    context = data.get("context_window") or {}
    model = (data.get("model") or {}).get("id")
    # A configured window above the model's context is capped at the model's.
    windows = [w for w in (compact_window(workspace.get("project_dir") or workspace.get("current_dir"), model),
                           context.get("context_window_size")) if w]
    point = compaction_point(min(windows)) if windows else None
    cells = 24 if columns is None or columns >= WIDE else 12
    usage = context.get("current_usage")
    ledger = _ledger_note(data.get("session_id"), now)
    if not (usage and point):
        return _fit([f"{DIM}{'░' * cells}  context: waiting for the first reply{RESET}", ledger], columns)
    tokens = usage_tokens(usage)
    share = tokens / point
    colour = GREEN if share < REARM_BELOW else YELLOW if tokens < warn_point(point) else RED
    filled = min(cells, round(share * cells))
    gauge = (f"{colour}{'█' * filled}{RESET}{DIM}{'░' * (cells - filled)}{RESET} "
             f"{colour}{_k(tokens)} / {_k(point)}  {share:.0%}{RESET}")
    if share >= 1:
        status = f"{RED}past the compaction point: compacts on the next prompt{RESET}"
    elif tokens >= warn_point(point):
        status = f"{YELLOW}compaction in {_k(point - tokens)}{RESET}"
    else:
        status = f"{DIM}{_k(point - tokens)} until compaction{RESET}"
    return _fit([gauge, status, ledger], columns)


def _ledger_note(session_id: Optional[str], now: float) -> Optional[str]:
    """When this session's ledger was last written — also a sign the plugin runs."""
    if not session_id:
        return None
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    folders = [Path(data)] if data else list(
        (config_dir() / "plugins" / "data").glob(f"{PLUGIN_NAME}-*"))
    ledgers = [f / "ledgers" / f"{checked(session_id)}.md" for f in folders]
    ledgers = [ledger for ledger in ledgers if ledger.exists()]
    if not ledgers:
        return f"{DIM}no ledger yet{RESET}"
    written = max(ledger.stat().st_mtime for ledger in ledgers)
    return f"{DIM}ledger {age_text(now - written)} ago{RESET}"


def _session_row(data: dict, now: float, columns: Optional[int]) -> str:
    model = (data.get("model") or {}).get("display_name", "?")
    effort = (data.get("effort") or {}).get("level")
    parts = [f"{DIM}{model}{' ' + effort if effort else ''}{RESET}"]
    workspace = data.get("workspace") or {}
    branch = (data.get("worktree") or {}).get("branch") or _git_branch(workspace.get("current_dir") or data.get("cwd"))
    if branch:
        parts.append(f"{DIM}{branch}{RESET}")
    pr = data.get("pr") or {}
    if pr.get("number"):
        parts.append(f"{DIM}PR #{pr['number']}{RESET}")
    limits = data.get("rate_limits") or {}
    for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
        limit = limits.get(key) or {}
        used = limit.get("used_percentage")
        if used is None:
            continue
        colour = RED if used >= 90 else YELLOW if used >= 70 else DIM
        resets = ""
        if key == "five_hour" and limit.get("resets_at"):
            resets = " until " + time.strftime("%H:%M", time.localtime(limit["resets_at"]))
        parts.append(f"{colour}{label} {used:.0f}%{resets}{RESET}")
    cache = _cache_note(data.get("prompt_cache") or {}, now)
    if cache:
        parts.append(cache)
    return _fit(parts, columns)


def _cache_note(cache: dict, now: float) -> Optional[str]:
    if not cache.get("caching_observed"):
        return None
    if not cache.get("warm"):
        recache = cache.get("recache_tokens_if_cold")
        cost = f": the next turn re-caches {_k(recache)}" if recache else ""
        return f"{YELLOW}cache cold{cost}{RESET}"
    expires = cache.get("expires_at")
    if expires and expires - now < CACHE_SOON:
        return f"{YELLOW}cache cold in {max(0, int((expires - now) // 60))} min{RESET}"
    return f"{DIM}cache warm{RESET}"


def _fit(parts: list, columns: Optional[int]) -> str:
    """Joins the parts, dropping the last ones until the row fits."""
    parts = [part for part in parts if part]
    while len(parts) > 1 and columns and len(ANSI.sub("", SEPARATOR.join(parts))) > columns:
        parts.pop()
    return SEPARATOR.join(parts)


def _k(tokens: int) -> str:
    return f"{round(tokens / 1000)}k"


def _git_branch(cwd: Optional[str]) -> Optional[str]:
    if not cwd:
        return None
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "branch", "--show-current"],
            capture_output=True, text=True, timeout=1, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() or None
