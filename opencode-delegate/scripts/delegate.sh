#!/usr/bin/env bash
set -euo pipefail
here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ "${1:-}" == "analyze" || "${1:-}" == "implement" ]]; then
  printf '%s\n' 'V1 positional invocation is intentionally retired. Use init/run/verify/review with a frozen contract; see SKILL.md.' >&2
  exit 2
fi
exec python3 "$here/delegate.py" "$@"
