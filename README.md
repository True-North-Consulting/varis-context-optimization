# Varis Context Optimization

A Claude Code plugin that makes a smaller compaction window safe to use.

Every turn of a Claude Code session re-reads the whole context, so the size of
the context is what a long session costs. A smaller `autoCompactWindow`
compacts earlier and keeps every turn cheaper, but each compaction replaces the
conversation with a lossy summary. This plugin carries the important state
across that compaction:

- **A session ledger.** Claude keeps a short Markdown file per session (goal,
  state, decisions, rejected approaches, open to-dos, pointers). The plugin
  reminds it to write the ledger, warns it before the compaction comes, and
  re-injects the ledger right after the compaction.
- **A verbatim record.** After a compaction the plugin also injects what it
  read from the transcript itself, not a summary: the user's messages (the
  first and the latest), the files edited, the last commands and the git state.
  This works even if Claude never wrote its ledger.
- **A search into the full transcript.** Claude gets a command that finds the
  exact details the summary dropped, such as error text, IDs or a path, on
  either side of every compaction.
- **A status line** that shows the context against the point where Claude Code
  will compact, how long ago the ledger was written, and the model, branch,
  PR, usage limits and prompt-cache state.

## Measured

Over two days of real sessions on one team's codebase, with the plugin and a
300k window, compared with the sessions before on a 1M window:

|                                          | Before | After  |
| ---------------------------------------- | -----: | -----: |
| Cost per turn (Opus 5.5 API list prices) | $0.136 | $0.067 |
| Average context per turn                 | 444k   | 165k   |
| Share of spend at 300k context or more   | 75 %   | 0 %    |
| Sessions that grew past 400k             | 24     | 0      |

Your numbers will differ. The `/varis-context-optimization:report` command
measures your own sessions before and after (see below).

The same marketplace also offers
[varis-plan-tracker](https://github.com/True-North-Consulting/varis-plan-tracker),
a live progress page for multi-package plans.

## Requirements

- Claude Code (the CLI, the desktop app or the IDE extensions). Plugins' hooks
  do not run in claude.ai chat.
- macOS, Linux or Windows, with Python 3.9 or newer on the `PATH` as
  `python3`, `python` or `py`. The plugin uses only the Python standard
  library.
- On Windows, Git for Windows: Claude Code then runs hooks in Git Bash, which
  the plugin's starter script needs. Without it Claude Code falls back to
  PowerShell, where the plugin does not run. WSL works too.
- `git` on the `PATH`, for the branch and commit shown in the record and the
  status line. Without it those parts are left out.

## Install

### From the Claude plugin directory (review pending)

The plugin has been submitted to Anthropic's plugin directory and is waiting
for review. Once it is listed, install it from the **Discover** tab in
`/plugin` in Claude Code, or from [claude.ai/directory](https://claude.ai/directory).
There is no marketplace to add first. Until then, use the marketplace below.

### From the True North Consulting marketplace

```
/plugin marketplace add True-North-Consulting/varis-context-optimization
/plugin install varis-context-optimization@true-north-consulting
```

Either way, run the setup command once in a new session:

```
/varis-context-optimization:setup
```

It checks four things a plugin is not allowed to set for itself and prints
what to add for each one. **It never changes your settings itself.**

1. **The compaction window.** `autoCompactWindow` in `~/.claude/settings.json`.
   300000 halved the cost per turn in the measurement above. Smaller is
   cheaper per turn, larger compacts less often. A value set per model with
   `/autocompact` (in `modelSettings`) is honoured too.
2. **The status line.** `statusLine` pointing at a small launcher the plugin
   keeps in its data directory. The launcher survives plugin updates.
3. **Permission to write the ledger.** A `Read` and an `Edit` rule for the
   plugin's `ledgers/` folder. Without them Claude asks before each ledger
   update.
4. **The compaction rules.** One `@…/rules.md` line for `~/.claude/CLAUDE.md`.
   It tells the compaction what to keep word for word. The rules must come
   from CLAUDE.md: in testing, compaction ignored the same rules when a hook
   injected them.

Settings take effect in sessions started afterwards.

## Measure your own savings

```
/varis-context-optimization:report --until 2026-10-01
/varis-context-optimization:report --since 2026-10-01
```

This reads the current project's transcripts and prints the cost per turn,
the average context, the spend by context size, the peak context and the
number of compactions. Costs are in relative units (input 1, cache read 0.1,
output 5), so the comparison holds whatever the model's price. Sessions are
counted by the day they started.

## What it runs, reads and writes

Everything stays on your machine. The plugin makes no network requests.

**Runs.** `sh scripts/run.sh` runs on these events. It starts
`scripts/context_optimization.py` with the first of `python3`, `python` and
`py` that is Python 3.9 or newer:

- `SessionStart`: injects the ledger rule. After a compaction it also injects
  the ledger, the record and the search command, in under 10,000 characters.
- `UserPromptSubmit` and `PostToolBatch`: injects a reminder or a warning when
  one is due, and otherwise nothing.
- The status line, if you set it up.

To show the git state it runs `git branch --show-current`,
`git log -1 --format=%h %s` and `git status --porcelain` in the session's
working directory.

**Reads:**

- the session transcript Claude Code passes to the hook;
- the settings files Claude Code reads for `autoCompactWindow`: managed,
  `.claude/settings.local.json` and `.claude/settings.json` in the project,
  and `~/.claude/settings.json`;
- for `report`, the current project's transcripts in `~/.claude/projects/`;
- for `setup`, `~/.claude/settings.json` and `~/.claude/CLAUDE.md`, to check
  them.

**Writes**, all in the plugin's data directory. Claude Code names it after
the plugin and the marketplace it came from, for example
`~/.claude/plugins/data/varis-context-optimization-true-north-consulting/`;
`/varis-context-optimization:setup` prints the exact path:

- `ledgers/<session>.md`, written by Claude, not by the plugin;
- `state/<session>.json`, which reminders have been given;
- `statusline.sh` and `rules.md`, rewritten at each session start when the
  installed version changed them.

It deletes ledgers and state files that have not been touched for 30 days, at
the start of a new session.

If you set `CLAUDE_CONFIG_DIR`, read every `~/.claude` above as that directory.

**What is in the context.** The ledger and the record hold your own messages
and file paths in plain text, on your disk. Like the rest of the conversation,
what is injected goes to the model. The ledger rule tells Claude never to put
secrets, credentials or personal data in the ledger.

## How the warning is timed

Claude Code compacts a little before the window is full: about 33k tokens
before it. A 1M window compacts at about 967k (documented), and a 300k window
compacted at about 267k (measured over 17 compactions). The plugin warns 40k
before that point, or a quarter of the point on a small window. If the ledger
is still not updated three hook calls later, it warns once more. It also
reminds Claude whenever the conversation has grown by 100k since the ledger
was last written.

The window is read the way Claude Code reads it:
`CLAUDE_CODE_AUTO_COMPACT_WINDOW` first, then the settings files from managed
to user. Within one file, a window set for the current model wins. A window
set with the `--autocompact` launch flag is not visible to hooks. In that case
the warning does not fire, but the ledger reminders still do.

## Development

```
python3 -m pytest -q
claude plugin validate --strict .
```

## License

MIT. See [LICENSE](LICENSE).
