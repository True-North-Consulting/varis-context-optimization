"""TNC Context Optimization: auto-compaction that keeps what matters."""

PLUGIN_NAME = "tnc-context-optimization"


class HookError(Exception):
    """Unexpected input; reported on stderr, never silently ignored."""
