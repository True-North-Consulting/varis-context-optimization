"""The ledger reminders: once before a compaction, again if that one is ignored,
and whenever the conversation has grown a lot since the ledger was written."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from .ledger import age_text, ledger_path, state_path
from .settings import REARM_BELOW, compact_window, compaction_point, warn_point
from .transcript import latest_call

# Context growth after which Claude is reminded of a ledger it has not
# touched — again after each further step of this size.
STALE_GROWTH = 100_000
# Hook calls (prompts and tool batches) after the warning without a ledger
# write, before the warning is repeated once, more firmly.
ESCALATE_AFTER = 3


def watch(event: dict) -> Optional[str]:
    if event.get("agent_id"):
        return None  # a subagent's tool call; its context is its own
    call = latest_call(Path(event["transcript_path"]))
    if call is None:
        return None
    tokens = call.tokens
    session = event["session_id"]
    ledger = ledger_path(session)
    state = _read_state(session)
    before = dict(state)
    written = ledger.stat().st_mtime if ledger.exists() else None
    note = None
    window = compact_window(os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd"), call.model)
    if window is not None:
        point = compaction_point(window)
        if state["warned"] and tokens < REARM_BELOW * point:
            state.update(warned=False, escalated=False, calls_since_warning=0)
        elif not state["warned"] and tokens >= warn_point(point):
            state.update(warned=True, escalated=False, calls_since_warning=0,
                         warned_ledger=written, nudged_tokens=tokens)
            note = (
                f"Context is at {tokens // 1000}k; auto-compaction comes at about "
                f"{point // 1000}k. Bring your session ledger ({ledger}) up to date now, "
                f"before continuing."
            )
        elif state["warned"] and not state["escalated"]:
            if written != state["warned_ledger"]:
                state["escalated"] = True  # done: the ledger was written after the warning
            else:
                state["calls_since_warning"] += 1
                if state["calls_since_warning"] >= ESCALATE_AFTER:
                    state["escalated"] = True
                    note = (
                        f"Your session ledger ({ledger}) is still not updated since the warning, "
                        f"and auto-compaction is about {max(0, point - tokens) // 1000}k away. "
                        f"Update it with your next tool call; what is not in it may be lost."
                    )
    if (written != state["ledger_written"] or state["ledger_tokens"] is None
            or tokens < state["ledger_tokens"]):
        # The ledger was just written, this is the first look, or a compaction
        # shrank the context (and re-injected the ledger): count from here.
        state.update(ledger_written=written, ledger_tokens=tokens, nudged_tokens=tokens)
    elif note is None and tokens - state["nudged_tokens"] >= STALE_GROWTH:
        state["nudged_tokens"] = tokens
        grown = (tokens - state["ledger_tokens"]) // 1000
        if written is None:
            note = (
                f"The session has grown by {grown}k without a session ledger. Unless it only "
                f"answers a quick question, write one now at {ledger}."
            )
        else:
            note = (
                f"Your session ledger ({ledger}) was last written {age_text(time.time() - written)} "
                f"ago, {grown}k tokens of conversation back. If the goal, the state, a decision, "
                f"a rejected approach or the next step has changed since, update it with a small "
                f"edit; if nothing has, carry on."
            )
    if state != before:
        _write_state(session, state)
    return note


def _read_state(session_id: str) -> dict:
    state = {"warned": False, "escalated": False, "calls_since_warning": 0, "warned_ledger": None,
             "ledger_written": None, "ledger_tokens": None, "nudged_tokens": None}
    try:
        state.update(json.loads(state_path(session_id).read_text(encoding="utf-8")))
    except FileNotFoundError:
        pass
    return state


def _write_state(session_id: str, state: dict) -> None:
    path = state_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")
