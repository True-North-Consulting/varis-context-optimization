---
description: Where this project's sessions spend their tokens, by session start date (e.g. /report --since 2026-10-01)
argument-hint: "[--since YYYY-MM-DD] [--until YYYY-MM-DD]"
---

Run this command and show its output to the user:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/context_optimization.py" report $ARGUMENTS
```

Costs are relative units (input 1, cache read 0.1, output 5), so a before and
after comparison holds whatever the model's price. To compare, run it once with
`--until` and once with `--since` the day the settings changed, and set the two
next to each other. Sessions are counted by the day they started.
