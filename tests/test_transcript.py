from __future__ import annotations

from conftest import BOUNDARY, assistant, user, write_transcript

from tnc_context.transcript import TAIL_START, activity, grep, latest_call


def test_the_latest_main_thread_call_with_its_model(isolated):
    transcript = write_transcript(isolated["tmp"] / "t.jsonl", [
        assistant(120000), user("next"), assistant(150000, model="claude-opus-5-5"),
        assistant(9000, sidechain=True),
    ])
    assert latest_call(transcript) == (150000, "claude-opus-5-5")


def test_after_a_compaction_the_context_is_unknown_until_the_next_call(isolated):
    path = isolated["tmp"] / "t.jsonl"
    write_transcript(path, [assistant(290000), BOUNDARY, user("go on")])
    assert latest_call(path) is None
    write_transcript(path, [assistant(290000), BOUNDARY, user("go on"), assistant(61000)])
    assert latest_call(path).tokens == 61000


def test_found_behind_tool_results_larger_than_the_first_tail(isolated):
    huge = {"type": "user", "message": {"content": [
        {"type": "tool_result", "content": "x" * (TAIL_START * 2)}]}}
    transcript = write_transcript(isolated["tmp"] / "t.jsonl", [assistant(180000), huge])
    assert latest_call(transcript).tokens == 180000


def test_a_failed_calls_stand_in_record_is_skipped(isolated):
    error = {"type": "assistant", "isApiErrorMessage": True,
             "message": {"content": [], "usage": {"input_tokens": 0, "output_tokens": 0}}}
    transcript = write_transcript(isolated["tmp"] / "t.jsonl", [assistant(260000), user("go"), error])
    assert latest_call(transcript).tokens == 260000


def test_a_transcript_without_calls(isolated):
    assert latest_call(write_transcript(isolated["tmp"] / "t.jsonl", [user("hello")])) is None


def test_activity_keeps_real_prompts_edits_and_commands(isolated):
    transcript = write_transcript(isolated["tmp"] / "t.jsonl", [
        user("Bitte den Export reparieren"),
        user("<command-name>/clear</command-name>"),
        user("[Request interrupted by user]"),
        user("meta note", isMeta=True),
        user("summary of before", isCompactSummary=True),
        user([{"type": "tool_result", "content": "output"}]),
        user([{"type": "text", "text": "und die Tests"}]),
        assistant(1000, tools=(("Edit", {"file_path": "/p/a.py"}), ("Bash", {"command": "pytest -q"}))),
        assistant(2000, tools=(("Write", {"file_path": "/p/b.py"}), ("Edit", {"file_path": "/p/a.py"}))),
        assistant(3000, sidechain=True, tools=(("Edit", {"file_path": "/p/sub.py"}),)),
    ])
    done = activity(transcript)
    assert done.prompts == ["Bitte den Export reparieren", "und die Tests"]
    assert done.edited == ["/p/b.py", "/p/a.py"]
    assert done.commands == ["pytest -q"]


def test_grep_finds_details_on_both_sides_of_a_compaction(isolated):
    tool_use = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": "gh pr view 4711"}}]}}
    result = {"type": "user", "message": {"content": [
        {"type": "tool_result", "content": [{"type": "text", "text": "Error: quota exceeded for PR 4711"}]}]}}
    transcript = write_transcript(isolated["tmp"] / "t.jsonl", [
        user("Bitte PR 4711 mergen"), tool_use, result, BOUNDARY, assistant(1000, text="4711 is merged"),
    ])
    lines = grep(transcript, "4711", limit=20, width=40).splitlines()
    assert len(lines) == 4
    assert lines[0].startswith("[compaction 0 · line 1] user:")
    assert "tool Bash" in lines[1] and "result" in lines[2]
    assert lines[3].startswith("[compaction 1 · line 5] claude:")


def test_grep_caps_its_output(isolated):
    transcript = write_transcript(isolated["tmp"] / "t.jsonl", [user(f"hit {i}") for i in range(30)])
    out = grep(transcript, "hit", limit=5, width=10).splitlines()
    assert len(out) == 6
    assert out[-1] == "(25 more matches — narrow the pattern)"


def test_grep_without_matches(isolated):
    transcript = write_transcript(isolated["tmp"] / "t.jsonl", [user("nothing")])
    assert grep(transcript, "absent", limit=5, width=10) == "no matches"
