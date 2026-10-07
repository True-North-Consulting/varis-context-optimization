"""Shared fixtures: every test gets its own home, project and plugin data dir.

The hooks run on every prompt and tool batch of everyone who installs the
plugin, so each path is pinned by a test: a regression would otherwise surface
as a compaction that silently lost its ledger.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from tnc_context import settings  # noqa: E402

SESSION = "0a1b2c3d-session"
BOUNDARY = {"type": "system", "subtype": "compact_boundary"}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    project = tmp_path / "project"
    (project / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
    monkeypatch.delenv("COLUMNS", raising=False)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    managed = tmp_path / "managed-settings.json"
    monkeypatch.setattr(settings, "MANAGED_SETTINGS", (managed,))
    return {"home": home, "project": project, "data": tmp_path / "data", "tmp": tmp_path,
            "managed": managed}


@pytest.fixture
def window(isolated):
    """A 300k window: compaction at 267k, the ledger warning at 227k."""
    write_settings(isolated["project"] / ".claude" / "settings.json", {"autoCompactWindow": 300000})
    return 300000


def write_settings(path: Path, values: dict) -> None:
    path.write_text(json.dumps(values), encoding="utf-8")


def assistant(tokens: int, *, sidechain: bool = False, text: str = "ok", model: str = "claude-test",
              tools: tuple = ()) -> dict:
    return {
        "type": "assistant",
        "isSidechain": sidechain,
        "timestamp": "2026-10-04T10:00:00.000Z",
        "message": {
            "id": f"msg-{tokens}-{text}",
            "model": model,
            "content": [{"type": "text", "text": text}]
            + [{"type": "tool_use", "name": name, "input": tool_input} for name, tool_input in tools],
            "usage": {
                "input_tokens": 2,
                "cache_read_input_tokens": tokens - 2 - 100,
                "cache_creation_input_tokens": 100,
                "output_tokens": 50,
            },
        },
    }


def user(text, **extra) -> dict:
    return {"type": "user", "message": {"content": text}, **extra}


def write_transcript(path: Path, records: list) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path
