## Context economy

Every turn re-reads the whole context, so its size is what a long session
costs; auto-compaction replaces it with a summary once it reaches the
`autoCompactWindow`. The Varis Context Optimization plugin's session ledger
carries the important state across that compaction (the SessionStart note
names the file).

### Compact instructions

When compacting, keep — word for word where it matters:
- the user's requests and decisions, quoted;
- worktree, branch, commits and PRs, and what is verified and how;
- decisions with their reasons, and approaches rejected with theirs;
- the open to-dos in order, with the very next step;
- exact identifiers: paths with line numbers, PR and issue numbers, IDs,
  commands, error text.

Drop file contents (they can be re-read), tool output already acted on and
finished detours. The session ledger is re-injected after the compaction, so
the summary need not repeat it.

### Keeping the context small

- Trim command output at the source — `| tail -n 40`, `grep -c`, `--quiet` —
  or send long output to a file in the scratchpad and grep it. Not where the
  exit status matters: a pipe replaces it with the last command's.
- Read large files with `offset`/`limit`; never re-read a file already in
  context.
- In the browser, read the page as text (`get_page_text`, `find`,
  `read_page`); take a screenshot only when the look itself is the question —
  one costs as much as a long file.
- Hand sweeps across many files to a subagent; only its answer enters this
  context.
