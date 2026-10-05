"""Reading a Claude Code session transcript (JSONL, one record per line)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterator, NamedTuple, Optional

# The transcript is read from its end; assistant records sit between tool
# results that can be hundreds of KB (screenshots), so the window grows.
TAIL_START = 512 * 1024
TAIL_MAX = 16 * 1024 * 1024
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


class Call(NamedTuple):
    tokens: int
    model: Optional[str]


class Activity(NamedTuple):
    """What a session did, read mechanically from its transcript."""

    prompts: list
    edited: list
    commands: list


def usage_tokens(usage: dict) -> int:
    """Context size of one API call: everything the model read as input."""
    return (
        usage.get("input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0)
    )


def is_compact_boundary(record: dict) -> bool:
    return record.get("type") == "system" and record.get("subtype") == "compact_boundary"


def latest_call(transcript: Path) -> Optional[Call]:
    """The main conversation's latest API call: its context size and model.

    None when nothing was called since the start or the last compaction.
    """
    size = transcript.stat().st_size
    tail = TAIL_START
    while True:
        with transcript.open("rb") as handle:
            handle.seek(max(0, size - tail))
            lines = handle.read().splitlines()
        whole_file = tail >= size
        if not whole_file:
            lines = lines[1:]  # the first line is cut mid-record
        for line in reversed(lines):
            try:
                record = json.loads(line)
            except ValueError:
                continue  # a record still being written
            if is_compact_boundary(record):
                return None
            if (record.get("type") != "assistant" or record.get("isSidechain")
                    or record.get("isApiErrorMessage")):
                continue  # a failed call's stand-in record carries zero usage
            message = record.get("message") or {}
            usage = message.get("usage")
            if usage and usage_tokens(usage):
                return Call(usage_tokens(usage), message.get("model"))
        if whole_file or tail >= TAIL_MAX:
            return None
        tail *= 4


def records(transcript: Path) -> Iterator[tuple]:
    """(line number, record) for each parseable line."""
    with transcript.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            try:
                yield number, json.loads(line)
            except ValueError:
                continue


def prompt_text(record: dict) -> Optional[str]:
    """What the user typed, for a record that is a real user prompt."""
    if (record.get("type") != "user" or record.get("isSidechain") or record.get("isMeta")
            or record.get("isCompactSummary")):
        return None
    content = (record.get("message") or {}).get("content")
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        content = "\n".join(b.get("text", "") for b in content
                            if isinstance(b, dict) and b.get("type") == "text")
    if not isinstance(content, str):
        return None
    text = content.strip()
    # Slash-command wrappers, command output and harness notices start with a tag.
    if not text or text.startswith("<") or text.startswith("[Request interrupted"):
        return None
    return text


def activity(transcript: Path) -> Activity:
    prompts, edited, commands = [], [], []
    for _, record in records(transcript):
        text = prompt_text(record)
        if text is not None:
            prompts.append(text)
            continue
        if record.get("type") != "assistant" or record.get("isSidechain"):
            continue
        for block in (record.get("message") or {}).get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            tool_input = block.get("input") or {}
            if block.get("name") in EDIT_TOOLS:
                path = tool_input.get("file_path") or tool_input.get("notebook_path")
                if path:
                    if path in edited:
                        edited.remove(path)
                    edited.append(path)
            elif block.get("name") == "Bash" and tool_input.get("command"):
                commands.append(tool_input["command"])
    return Activity(prompts, edited, commands)


def transcript_texts(transcript: Path) -> Iterator[tuple]:
    """(line number, compaction segment, role, text) for each searchable part."""
    segment = 0
    for number, record in records(transcript):
        kind = record.get("type")
        if is_compact_boundary(record):
            segment += 1
            continue
        if kind not in ("user", "assistant"):
            continue
        content = (record.get("message") or {}).get("content")
        if isinstance(content, str):
            yield number, segment, kind, content
            continue
        for block in content or []:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                yield number, segment, "claude" if kind == "assistant" else "user", block["text"]
            elif block_type == "tool_use":
                yield number, segment, f"tool {block.get('name')}", json.dumps(block.get("input"))
            elif block_type == "tool_result":
                yield number, segment, "result", _result_text(block.get("content"))


def _result_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ""


def grep(transcript: Path, pattern: str, limit: int, width: int) -> str:
    regex = re.compile(pattern, re.IGNORECASE)
    hits = []
    total = 0
    for number, segment, role, text in transcript_texts(transcript):
        match = regex.search(text)
        if not match:
            continue
        total += 1
        if len(hits) < limit:
            start = max(0, match.start() - width)
            excerpt = " ".join(text[start:match.end() + width].split())
            hits.append(f"[compaction {segment} · line {number}] {role}: …{excerpt}…")
    if total > limit:
        hits.append(f"({total - limit} more matches — narrow the pattern)")
    return "\n".join(hits) if hits else "no matches"
