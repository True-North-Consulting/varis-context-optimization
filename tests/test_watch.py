from __future__ import annotations

import json
import os

import pytest
from conftest import BOUNDARY, SESSION, assistant, user, write_transcript

from varis_context import HookError
from varis_context.ledger import ledger_path, state_path
from varis_context.watch import watch


def event(transcript, **extra) -> dict:
    return {"session_id": SESSION, "transcript_path": str(transcript),
            "hook_event_name": "PostToolBatch", **extra}


def at(isolated, *tokens: int):
    """Writes a transcript whose latest call has `tokens[-1]` of context."""
    return write_transcript(isolated["tmp"] / "t.jsonl", [assistant(t) for t in tokens])


def write_ledger(when: float) -> None:
    ledger = ledger_path(SESSION)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("## Goal", encoding="utf-8")
    os.utime(ledger, (when, when))


def test_quiet_below_the_warning(isolated, window):
    assert watch(event(at(isolated, 220000))) is None


def test_warns_before_the_compaction_point_not_at_the_window(isolated, window):
    note = watch(event(at(isolated, 228000)))
    assert note.startswith("Context is at 228k; auto-compaction comes at about 267k.")
    assert str(ledger_path(SESSION)) in note


def test_an_ignored_warning_is_repeated_once_more_firmly(isolated, window):
    assert watch(event(at(isolated, 230000))) is not None
    assert watch(event(at(isolated, 232000))) is None
    assert watch(event(at(isolated, 234000))) is None
    again = watch(event(at(isolated, 236000)))
    assert "still not updated since the warning" in again and "31k away" in again
    assert watch(event(at(isolated, 238000))) is None
    assert watch(event(at(isolated, 240000))) is None


def test_a_ledger_written_after_the_warning_ends_it(isolated, window):
    write_ledger(1000)
    assert watch(event(at(isolated, 230000))) is not None
    write_ledger(2000)
    for tokens in (232000, 234000, 236000, 238000):
        assert watch(event(at(isolated, tokens))) is None


def test_the_warning_rearms_after_a_compaction(isolated, window):
    path = isolated["tmp"] / "t.jsonl"
    assert watch(event(at(isolated, 230000))) is not None
    write_transcript(path, [assistant(270000), BOUNDARY, user("go on")])
    assert watch(event(path)) is None  # no call since the compaction yet
    write_transcript(path, [assistant(270000), BOUNDARY, user("go on"), assistant(70000)])
    assert watch(event(path)) is None
    assert "Context is at 229k" in watch(event(at(isolated, 70000, 229000)))


def test_a_failed_call_does_not_rearm_the_warning(isolated, window):
    path = at(isolated, 230000)
    assert watch(event(path)) is not None
    error = {"type": "assistant", "isApiErrorMessage": True,
             "message": {"content": [], "usage": {"input_tokens": 0, "output_tokens": 0}}}
    write_transcript(path, [assistant(230000), error])
    write_ledger(5000)
    assert watch(event(path)) is None


def test_the_window_set_for_the_model_counts(isolated):
    (isolated["home"] / ".claude" / "settings.json").write_text(json.dumps(
        {"modelSettings": {"claude-test": {"autoCompactWindow": 200000}}}), encoding="utf-8")
    assert "auto-compaction comes at about 167k" in watch(event(at(isolated, 140000)))


def test_subagent_tool_calls_are_ignored(isolated, window):
    assert watch(event(at(isolated, 290000), agent_id="sub-1")) is None
    assert not state_path(SESSION).exists()


def test_without_a_window_no_warning(isolated):
    assert watch(event(at(isolated, 900000))) is None


def test_freshness_counts_from_the_last_ledger_write(isolated):
    write_ledger(1000)
    seen = [watch(event(at(isolated, tokens))) for tokens in (100000, 150000, 205000, 250000, 306000)]
    assert seen[0] is None and seen[1] is None and seen[3] is None
    assert "105k tokens of conversation back" in seen[2] and str(ledger_path(SESSION)) in seen[2]
    assert "206k tokens of conversation back" in seen[4]


def test_rewriting_the_ledger_restarts_the_count(isolated):
    write_ledger(1000)
    assert watch(event(at(isolated, 100000))) is None
    assert watch(event(at(isolated, 201000))) is not None
    write_ledger(2000)
    assert watch(event(at(isolated, 210000))) is None
    assert watch(event(at(isolated, 300000))) is None
    assert "101k tokens of conversation back" in watch(event(at(isolated, 311000)))


def test_a_session_without_a_ledger_is_asked_for_one(isolated):
    assert watch(event(at(isolated, 50000))) is None
    assert watch(event(at(isolated, 100000))) is None
    assert "grown by 101k without a session ledger" in watch(event(at(isolated, 151000)))


def test_the_warning_and_the_reminder_never_stack(isolated, window):
    assert watch(event(at(isolated, 120000))) is None
    note = watch(event(at(isolated, 230000)))
    assert note.startswith("Context is at 230k") and "grown by" not in note


def test_after_a_compaction_the_count_starts_from_the_smaller_context(isolated):
    path = isolated["tmp"] / "t.jsonl"
    assert watch(event(at(isolated, 200000))) is None
    write_transcript(path, [assistant(200000), BOUNDARY, user("go on"), assistant(60000)])
    assert watch(event(path)) is None
    assert watch(event(at(isolated, 60000, 155000))) is None
    assert "grown by 101k" in watch(event(at(isolated, 60000, 161000)))


def test_a_state_file_from_an_older_version_still_reads(isolated, window):
    path = state_path(SESSION)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"warned": False, "ledger_written": None, "ledger_tokens": 100000,
                                "nudged_tokens": 100000}), encoding="utf-8")
    assert watch(event(at(isolated, 230000))) is not None
    assert json.loads(path.read_text())["warned"] is True


def test_a_bad_session_id_writes_no_state(isolated, window):
    with pytest.raises(HookError):
        watch({"session_id": "../x", "transcript_path": str(at(isolated, 290000))})
    assert not (isolated["data"] / "state").exists()
