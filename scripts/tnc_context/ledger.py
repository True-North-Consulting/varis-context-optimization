"""The session ledger: where it lives, the rule for Claude, and what comes back
after a compaction."""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

from . import HookError, files
from .transcript import Activity, activity

# What a SessionStart hook can inject is capped at 10,000 characters.
CONTEXT_MAX_CHARS = 9500
# Claude's ledger and the plugin's own record share that budget.
LEDGER_MAX_CHARS = 5500
PROMPT_MAX_CHARS = 600
EDITED_SHOWN = 12
COMMANDS_SHOWN = 5
COMMAND_MAX_CHARS = 140
# Ledgers and state files of sessions untouched this long are deleted.
RETENTION_DAYS = 30

LEDGER_RULE = """\
Your session ledger is {ledger}. It is your working memory across \
auto-compaction, which can happen at any moment: create it at the first \
milestone, then update it with a small edit at each later one — a decision of \
the user's, an approach rejected, a commit or PR, a gotcha found. Use these \
`## ` headings, in this order: Goal (the user's requests, quoted word for \
word) · State (branch, commits, what is verified and how) · Decisions (with \
why) · Rejected (with why) · Open (to-dos in order, next step first) · \
Pointers (path:line, PR numbers, IDs, exact error text). Stay under {limit:,} \
characters; never put secrets, credentials or personal data in it. A session \
that only answers a quick question needs no ledger."""


def data_dir() -> Path:
    value = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not value:
        raise HookError("CLAUDE_PLUGIN_DATA is unset; run this as the plugin's hook")
    return Path(value)


def ledger_path(session_id: str) -> Path:
    return data_dir() / "ledgers" / f"{checked(session_id)}.md"


def state_path(session_id: str) -> Path:
    return data_dir() / "state" / f"{checked(session_id)}.json"


def checked(session_id: str) -> str:
    """A session id safe to use as a file name inside the data dir."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", session_id or ""):
        raise HookError(f"unexpected session_id: {session_id!r}")
    return session_id


def rule(ledger: Path) -> str:
    return LEDGER_RULE.format(ledger=ledger, limit=LEDGER_MAX_CHARS)


def grep_command(transcript: str) -> str:
    return files.command("grep", transcript, "<regex>")


def session_start(event: dict, now: Optional[float] = None) -> str:
    now = time.time() if now is None else now
    source = event["source"]
    ledger = ledger_path(event["session_id"])
    ledger.parent.mkdir(parents=True, exist_ok=True)
    files.install(data_dir())
    if source == "startup":
        prune(now)
    if source != "compact":
        return rule(ledger)
    head = ["Auto-compaction has just replaced the earlier conversation with a summary."]
    if ledger.exists():
        text = ledger.read_text(encoding="utf-8")
        age = age_text(now - ledger.stat().st_mtime)
        if len(text) > LEDGER_MAX_CHARS:
            head.append(
                f"Your session ledger ({ledger}, updated {age} ago) is {len(text):,} characters, "
                f"over the {LEDGER_MAX_CHARS:,} that fit here: Read it now, then tighten it."
            )
        else:
            head.append(
                f"Your session ledger ({ledger}, updated {age} ago) follows. Where it and the "
                f"summary disagree, the more recent information wins.\n\n{text.strip()}"
            )
    else:
        head.append(f"No session ledger was written before this compaction ({ledger}).")
    tail = [
        "Exact details the summary dropped — commands, error text, the user's words, IDs — "
        "are still in the full transcript. Search it instead of guessing:\n"
        f"  {grep_command(event['transcript_path'])}",
        rule(ledger),
    ]
    budget = CONTEXT_MAX_CHARS - len("\n\n".join(head + tail)) - 2
    record = recorded(activity(Path(event["transcript_path"])), event.get("cwd"), budget)
    return "\n\n".join(head + ([record] if record else []) + tail)


def recorded(done: Activity, cwd: Optional[str], budget: int) -> str:
    """The plugin's own record of the session, verbatim, within `budget` chars.

    It does not depend on Claude having kept its ledger: the user's words, the
    files edited, the last commands and the git state come from the transcript.
    """
    lines = ["Recorded by the plugin from the transcript (verbatim, not a summary):"]
    git = git_state(cwd)
    if git:
        lines.append(f"Git: {git}")
    if done.edited:
        shown = [_relative(p, cwd) for p in reversed(done.edited[-EDITED_SHOWN:])]
        more = len(done.edited) - len(shown)
        lines.append("Files edited, newest first: " + ", ".join(shown)
                     + (f" (+{more} more)" if more > 0 else ""))
    if done.commands:
        lines.append("Last commands:")
        lines += [f"  $ {_clip(c.splitlines()[0], COMMAND_MAX_CHARS)}"
                  for c in done.commands[-COMMANDS_SHOWN:]]
    fixed = "\n".join(lines)
    room = budget - len(fixed) - 1
    prompts = _prompts(done.prompts, room)
    text = "\n".join([lines[0], prompts] + lines[1:]) if prompts else fixed
    return text if len(text) <= budget else ""


def _prompts(prompts: list, room: int) -> str:
    """The first prompt (the opening ask) and as many of the latest as fit."""
    if not prompts:
        return ""
    numbered = [f"  [{i}] “{_clip(p, PROMPT_MAX_CHARS)}”" for i, p in enumerate(prompts, 1)]

    def block(kept: list) -> str:
        omitted = len(numbered) - len(kept)
        title = (f"The user's messages ({len(prompts)}; the first and the latest"
                 + (f", {omitted} in between omitted — grep for them):" if omitted else "):"))
        return "\n".join([title] + kept)

    kept = [numbered[0]]
    for line in reversed(numbered[1:]):
        if len(block([kept[0], line] + kept[1:])) > room:
            break
        kept.insert(1, line)
    text = block(kept)
    return text if len(text) <= room else ""


def git_state(cwd: Optional[str]) -> Optional[str]:
    """Branch, HEAD and uncommitted count of the session's working dir."""
    if not cwd:
        return None
    branch = _git(cwd, "branch", "--show-current")
    head = _git(cwd, "log", "-1", "--format=%h %s")
    if head is None:
        return None
    status = _git(cwd, "status", "--porcelain") or ""
    dirty = len([line for line in status.splitlines() if line.strip()])
    parts = [f"branch {branch or '(detached)'}", f"HEAD {_clip(head, 90)}"]
    parts.append(f"{dirty} uncommitted" if dirty else "clean")
    return f"{cwd} · " + " · ".join(parts)


def _git(cwd: str, *args: str) -> Optional[str]:
    try:
        result = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True,
                                timeout=2, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def prune(now: float) -> None:
    cutoff = now - RETENTION_DAYS * 86400
    for folder in ("ledgers", "state"):
        for path in (data_dir() / folder).glob("*"):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
            except FileNotFoundError:
                continue  # another session pruned it first


def age_text(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60} min"


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _relative(path: str, cwd: Optional[str]) -> str:
    if not cwd:
        return path
    try:
        return str(Path(path).relative_to(cwd))
    except ValueError:
        return path  # outside the working dir
