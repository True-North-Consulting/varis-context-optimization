from __future__ import annotations

import datetime as dt
import importlib.util
import io
import json
import subprocess
import sys

from conftest import ROOT, SESSION, assistant, user, write_settings, write_transcript

from varis_context import files
from varis_context.report import report, transcripts_dir

_spec = importlib.util.spec_from_file_location("context_optimization", ROOT / "scripts" / "context_optimization.py")
entry = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(entry)


def run_main(argv, stdin, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(stdin)))
    code = entry.main(argv)
    return code, capsys.readouterr()


def test_watch_emits_hook_json_for_the_firing_event(isolated, window, monkeypatch, capsys):
    transcript = write_transcript(isolated["tmp"] / "t.jsonl", [assistant(240000)])
    event = {"session_id": SESSION, "transcript_path": str(transcript), "hook_event_name": "UserPromptSubmit"}
    code, out = run_main(["watch"], event, monkeypatch, capsys)
    assert code == 0
    payload = json.loads(out.out)["hookSpecificOutput"]
    assert payload["hookEventName"] == "UserPromptSubmit"
    assert "240k" in payload["additionalContext"]


def test_a_quiet_hook_prints_nothing(isolated, window, monkeypatch, capsys):
    transcript = write_transcript(isolated["tmp"] / "t.jsonl", [assistant(1000)])
    event = {"session_id": SESSION, "transcript_path": str(transcript), "hook_event_name": "PostToolBatch"}
    code, out = run_main(["watch"], event, monkeypatch, capsys)
    assert code == 0 and out.out == ""


def test_unexpected_input_is_reported_on_stderr(isolated, monkeypatch, capsys):
    code, out = run_main(["session-start"], {"session_id": SESSION}, monkeypatch, capsys)
    assert code == 1
    assert out.err.startswith("varis-context-optimization session-start:")
    assert out.out == ""


def test_the_hooks_call_existing_subcommands():
    hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    assert set(hooks) == {"SessionStart", "UserPromptSubmit", "PostToolBatch"}
    for entries in hooks.values():
        for item in entries:
            for hook in item["hooks"]:
                command = hook["command"]
                assert command.startswith('python3 "${CLAUDE_PLUGIN_ROOT}/scripts/context_optimization.py" ')
                assert command.split()[-1] in ("session-start", "watch")


def test_the_commands_call_existing_subcommands():
    for name, sub in (("setup", "setup"), ("report", "report")):
        text = (ROOT / "commands" / f"{name}.md").read_text(encoding="utf-8")
        assert f'"${{CLAUDE_PLUGIN_ROOT}}/scripts/context_optimization.py" {sub}' in text


def test_the_entry_script_runs_on_its_own(isolated):
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "context_optimization.py"), "--help"],
                            capture_output=True, text=True, check=True)
    assert "session-start" in result.stdout


# --- setup and the stable files -------------------------------------------------


def test_setup_installs_the_files_and_prints_what_is_missing(isolated, monkeypatch, capsys):
    code, out = run_main(["setup", "--project", str(isolated["project"])], {}, monkeypatch, capsys)
    assert code == 0
    data = isolated["data"]
    assert files.launcher_path(data).exists() and files.rules_path(data).exists()
    assert out.out.count("✘") == 4
    assert json.dumps(f'python3 "{files.launcher_path(data)}"') in out.out
    assert f"@{files.rules_path(data)}" in out.out


def test_setup_ticks_what_is_in_place(isolated, monkeypatch, capsys):
    data = isolated["data"]
    write_settings(isolated["home"] / ".claude" / "settings.json", {
        "autoCompactWindow": 300000,
        "statusLine": {"type": "command", "command": f'python3 "{files.launcher_path(data)}"'},
        "permissions": {"allow": [f"Read({data}/ledgers/**)", f"Edit({data}/ledgers/**)"]},
    })
    (isolated["home"] / ".claude" / "CLAUDE.md").write_text(f"@{files.rules_path(data)}\n", encoding="utf-8")
    code, out = run_main(["setup"], {}, monkeypatch, capsys)
    assert code == 0 and out.out.count("✔") == 4 and "✘" not in out.out
    assert "compacts at about 267,000" in out.out


def test_setup_writes_no_settings(isolated, monkeypatch, capsys):
    run_main(["setup"], {}, monkeypatch, capsys)
    assert not (isolated["home"] / ".claude" / "settings.json").exists()
    assert not (isolated["home"] / ".claude" / "CLAUDE.md").exists()


def test_setup_needs_a_data_dir(isolated, monkeypatch, capsys):
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA")
    code, out = run_main(["setup"], {}, monkeypatch, capsys)
    assert code == 1 and "--data" in out.err


def test_the_launcher_runs_the_statusline(isolated):
    files.install(isolated["data"])
    status = {"session_id": SESSION, "model": {"display_name": "Opus"}, "workspace": {},
              "context_window": {"context_window_size": 1000000, "current_usage": None}}
    result = subprocess.run([sys.executable, str(files.launcher_path(isolated["data"]))],
                            input=json.dumps(status), capture_output=True, encoding="utf-8", check=True)
    assert "waiting for the first reply" in result.stdout


# --- report -----------------------------------------------------------------------


def session_file(folder, name, started, tokens):
    records = [dict(user("go"), timestamp=started)]
    records += [dict(assistant(t, text=str(i)), timestamp=started) for i, t in enumerate(tokens)]
    return write_transcript(folder / f"{name}.jsonl", records)


def test_the_report_selects_sessions_by_start_date(isolated):
    folder = transcripts_dir(isolated["project"])
    folder.mkdir(parents=True)
    session_file(folder, "before", "2026-10-01T09:00:00Z", [450000, 500000])
    session_file(folder, "after", "2026-10-04T09:00:00Z", [100000, 150000, 200000])
    # A session started before the cut-off stays "before" however late it ran.
    every = report(isolated["project"], None, None)
    after = report(isolated["project"], dt.date(2026, 10, 4), None)
    before = report(isolated["project"], None, dt.date(2026, 10, 4))
    assert every.startswith("2 sessions, 5 turns")
    assert after.startswith("1 sessions, 3 turns") and "average context 150k" in after
    assert before.startswith("1 sessions, 2 turns") and "sessions above 400k: 1" in before


def test_the_report_of_an_empty_range(isolated):
    transcripts_dir(isolated["project"]).mkdir(parents=True)
    assert report(isolated["project"], dt.date(2030, 1, 1), None).startswith("no sessions")


def test_setup_and_report_follow_claude_config_dir(isolated, monkeypatch, capsys):
    other = isolated["tmp"] / "profile"
    other.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(other))
    code, out = run_main(["setup"], {}, monkeypatch, capsys)
    assert code == 0 and f"Add to {other / 'settings.json'}" in out.out
    assert transcripts_dir(isolated["project"]).parent == other / "projects"


def test_setup_accepts_the_paths_written_out_or_with_a_tilde(isolated, monkeypatch, capsys):
    data = isolated["home"] / ".claude" / "plugins" / "data" / "x"
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
    write_settings(isolated["home"] / ".claude" / "settings.json", {"permissions": {"allow": [
        f"Read({data}/ledgers/**)", "Edit(~/.claude/plugins/data/x/ledgers/**)"]}})
    (isolated["home"] / ".claude" / "CLAUDE.md").write_text("@~/.claude/plugins/data/x/rules.md\n",
                                                           encoding="utf-8")
    code, out = run_main(["setup"], {}, monkeypatch, capsys)
    assert "✔ ledger reads and writes allowed" in out.out
    assert "✔ compact rules imported" in out.out
