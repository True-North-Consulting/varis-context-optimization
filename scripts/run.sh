#!/bin/sh
# Starts the plugin with the first Python 3.9+ this system knows by name:
# `python3` on macOS and Linux, `python` or `py` on Windows (Git Bash), where
# `python3` may be the Microsoft Store stub that only opens the Store.
case $0 in
  */*) dir=${0%/*} ;;
  *\\*) dir=${0%\\*} ;;
  *) dir=. ;;
esac
for python in python3 python py; do
  if command -v "$python" >/dev/null 2>&1 &&
    "$python" -c 'import sys; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1; then
    exec "$python" "$dir/context_optimization.py" "$@"
  fi
done
echo "tnc-context-optimization: no Python 3.9 or newer found (tried python3, python, py)" >&2
exit 1
