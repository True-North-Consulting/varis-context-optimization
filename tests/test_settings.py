from __future__ import annotations

import pytest
from conftest import write_settings

from varis_context import HookError
from varis_context.settings import compact_window, compaction_point, warn_point


def test_window_unset_everywhere_is_none(isolated):
    assert compact_window(str(isolated["project"])) is None


def test_window_precedence_env_managed_local_project_user(isolated, monkeypatch):
    project = str(isolated["project"])
    write_settings(isolated["home"] / ".claude" / "settings.json", {"autoCompactWindow": 100000})
    assert compact_window(project) == 100000
    write_settings(isolated["project"] / ".claude" / "settings.json", {"autoCompactWindow": 200000})
    assert compact_window(project) == 200000
    write_settings(isolated["project"] / ".claude" / "settings.local.json", {"autoCompactWindow": 250000})
    assert compact_window(project) == 250000
    write_settings(isolated["managed"], {"autoCompactWindow": 350000})
    assert compact_window(project) == 350000
    monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "400000")
    assert compact_window(project) == 400000


def test_files_without_the_key_are_skipped(isolated):
    write_settings(isolated["project"] / ".claude" / "settings.json", {"model": "opus"})
    write_settings(isolated["home"] / ".claude" / "settings.json", {"autoCompactWindow": 300000})
    assert compact_window(str(isolated["project"])) == 300000


def test_a_window_for_the_model_wins_within_its_file(isolated):
    write_settings(isolated["home"] / ".claude" / "settings.json", {
        "autoCompactWindow": 500000,
        "modelSettings": {"claude-opus-5-5": {"autoCompactWindow": 300000}},
    })
    project = str(isolated["project"])
    assert compact_window(project, "claude-opus-5-5[1m]") == 300000
    assert compact_window(project, "Claude-Opus-5-5") == 300000
    assert compact_window(project, "claude-sonnet-5-5") == 500000
    assert compact_window(project) == 500000


def test_a_closer_file_wins_over_a_model_window_further_out(isolated):
    write_settings(isolated["home"] / ".claude" / "settings.json",
                   {"modelSettings": {"claude-x": {"autoCompactWindow": 300000}}})
    write_settings(isolated["project"] / ".claude" / "settings.json", {"autoCompactWindow": 200000})
    assert compact_window(str(isolated["project"]), "claude-x") == 200000


@pytest.mark.parametrize("value", ["300k", True, 0, -5, None, 33000])
def test_window_rejects_what_is_not_a_usable_token_count(isolated, value):
    write_settings(isolated["project"] / ".claude" / "settings.json", {"autoCompactWindow": value})
    with pytest.raises(HookError):
        compact_window(str(isolated["project"]))


def test_window_rejects_broken_settings_json(isolated):
    (isolated["project"] / ".claude" / "settings.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(HookError, match="not valid JSON"):
        compact_window(str(isolated["project"]))


def test_an_unreadable_managed_file_is_skipped(isolated, monkeypatch):
    write_settings(isolated["managed"], {"autoCompactWindow": 350000})
    isolated["managed"].chmod(0)
    write_settings(isolated["home"] / ".claude" / "settings.json", {"autoCompactWindow": 300000})
    try:
        assert compact_window(str(isolated["project"])) == 300000
    finally:
        isolated["managed"].chmod(0o644)


def test_the_compaction_and_warning_points():
    assert compaction_point(300000) == 267000
    assert warn_point(267000) == 227000
    assert compaction_point(1000000) == 967000
    assert warn_point(967000) == 927000
    # On a small window the warning comes a quarter of the point early.
    assert warn_point(compaction_point(100000)) == 67000 - 16750


def test_claude_config_dir_moves_the_user_settings(isolated, monkeypatch):
    other = isolated["tmp"] / "profile"
    other.mkdir()
    write_settings(isolated["home"] / ".claude" / "settings.json", {"autoCompactWindow": 300000})
    write_settings(other / "settings.json", {"autoCompactWindow": 200000})
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(other))
    assert compact_window(None) == 200000
