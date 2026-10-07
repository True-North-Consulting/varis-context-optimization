from __future__ import annotations

import os
import re
import time
from pathlib import Path

import pytest
from conftest import SESSION, write_settings

from tnc_context.statusline import RED, YELLOW, statusline

NOW = 1_800_000_000.0


def status_input(project: Path, tokens, **extra) -> dict:
    usage = None if tokens is None else {
        "input_tokens": 1000, "cache_read_input_tokens": tokens - 1000, "cache_creation_input_tokens": 0}
    data = {
        "session_id": SESSION,
        "model": {"id": "claude-test", "display_name": "Opus"},
        "workspace": {"current_dir": str(project), "project_dir": str(project)},
        "context_window": {"context_window_size": 1000000, "current_usage": usage},
    }
    data.update(extra)
    return data


def rows(data: dict) -> list:
    return [re.sub(r"\033\[[0-9;]*m", "", row) for row in statusline(data, now=NOW).split("\n")]


def test_the_bar_fills_toward_the_compaction_point(isolated, window):
    context, session = rows(status_input(isolated["project"], 180000))
    assert context.startswith("█" * 16 + "░" * 8 + " 180k / 267k  67%")
    assert "87k until compaction" in context
    assert session.startswith("Opus")


def test_past_the_warning_the_bar_turns_red(isolated, window):
    data = status_input(isolated["project"], 240000)
    assert RED in statusline(data, now=NOW).split("\n")[0]
    assert "compaction in 27k" in rows(data)[0]
    assert YELLOW in statusline(status_input(isolated["project"], 180000), now=NOW)


def test_past_the_compaction_point_says_what_happens_next(isolated, window):
    context = rows(status_input(isolated["project"], 300000))[0]
    assert context.startswith("█" * 24 + " 300k / 267k  112%")
    assert "past the compaction point: compacts on the next prompt" in context


def test_a_smaller_model_window_wins(isolated, window):
    data = status_input(isolated["project"], 150000)
    data["context_window"]["context_window_size"] = 200000
    assert "150k / 167k  90%" in rows(data)[0]


def test_the_window_set_for_the_model_counts(isolated):
    write_settings(isolated["home"] / ".claude" / "settings.json",
                   {"modelSettings": {"claude-test": {"autoCompactWindow": 300000}}})
    assert "100k / 267k" in rows(status_input(isolated["project"], 100000))[0]


def test_without_a_configured_window_the_model_window_counts(isolated):
    assert "100k / 967k  10%" in rows(status_input(isolated["project"], 100000))[0]


def test_before_the_first_reply(isolated, window):
    assert "context: waiting for the first reply" in rows(status_input(isolated["project"], None))[0]


def test_the_ledger_age_shows_that_the_plugin_runs(isolated, window, monkeypatch):
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA")
    data = status_input(isolated["project"], 50000)
    assert rows(data)[0].endswith("no ledger yet")
    ledger = (isolated["home"] / ".claude" / "plugins" / "data"
              / "tnc-context-optimization-true-north-consulting" / "ledgers" / f"{SESSION}.md")
    ledger.parent.mkdir(parents=True)
    ledger.write_text("## Goal", encoding="utf-8")
    os.utime(ledger, (NOW - 240, NOW - 240))
    assert rows(data)[0].endswith("ledger 4 min ago")


def test_the_session_row(isolated, window):
    data = status_input(
        isolated["project"], 50000,
        effort={"level": "high"},
        worktree={"branch": "feat/statusline-bar"},
        pr={"number": 385},
        rate_limits={"five_hour": {"used_percentage": 34.4, "resets_at": NOW + 3600},
                     "seven_day": {"used_percentage": 92}},
        prompt_cache={"caching_observed": True, "warm": True, "expires_at": NOW + 3000},
    )
    resets = time.strftime("%H:%M", time.localtime(NOW + 3600))
    assert rows(data)[1] == f"Opus high · feat/statusline-bar · PR #385 · 5h 34% until {resets} · 7d 92% · cache warm"
    assert RED in statusline(data, now=NOW).split("\n")[1]


@pytest.mark.parametrize("cache, note", [
    ({"caching_observed": True, "warm": False, "recache_tokens_if_cold": 690000},
     "cache cold: the next turn re-caches 690k"),
    ({"caching_observed": True, "warm": True, "expires_at": NOW + 240}, "cache cold in 4 min"),
    ({"caching_observed": False}, None),
])
def test_the_cache_note(isolated, window, cache, note):
    session = rows(status_input(isolated["project"], 50000, prompt_cache=cache))[1]
    if note:
        assert session.endswith(note)
    else:
        assert "cache" not in session


def test_rows_drop_their_last_parts_to_fit_the_terminal(isolated, window, monkeypatch):
    monkeypatch.setenv("COLUMNS", "40")
    data = status_input(isolated["project"], 180000, rate_limits={"five_hour": {"used_percentage": 34}})
    context, session = rows(data)
    assert context == "█" * 8 + "░" * 4 + " 180k / 267k  67%"
    assert len(session) <= 40
