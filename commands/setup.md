---
description: Check and print the settings Varis Context Optimization needs (compaction window, statusline, ledger permissions, compact rules)
---

Run this command and show its output to the user unchanged:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" setup --data "${CLAUDE_PLUGIN_DATA}"
```

Then explain each line marked ✘ in one sentence. Do not edit any settings file
or CLAUDE.md yourself unless the user asks you to; if they do, merge the
printed keys into the existing file instead of replacing it, and show the diff.
