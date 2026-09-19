#!/usr/bin/env bash
# Pre-commit gate: unit + contract + offline eval + demo-path tests. Must pass with NO .env present.
set -euo pipefail
cd "$(dirname "$0")/.."
# Interpreter: an explicit $PYTHON wins, then the project venv, then whatever
# python3 is on PATH. A reviewer who has not activated the venv still gets a run.
if [ -n "${PYTHON:-}" ]; then PY="$PYTHON"
elif [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"
else PY="python3"; fi

# The system Python on macOS is 3.9 and fails later with an opaque pydantic import
# error, so fail here with an actionable message instead.
if ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
  echo "ERROR: '$PY' is not Python 3.11+ (found: $("$PY" --version 2>&1 || echo 'not runnable'))." >&2
  echo "       Activate the project venv ('source .venv/bin/activate') or run:" >&2
  echo "         PYTHON=.venv/bin/python scripts/check_all.sh" >&2
  exit 2
fi

# Offline eval writes into a scratch dir: the gate must not dirty the committed
# results in assignment-a/evals/results/ (they carry a timestamp and a git hash,
# so every run would otherwise show up as a diff). Regenerate those deliberately:
#   python assignment-a/evals/run_eval.py --offline
EVAL_OUT="$(mktemp -d)"
trap 'rm -rf "$EVAL_OUT"' EXIT

# -m "not live": live tests bill a real provider. pyproject's addopts already
# excludes them; repeated here so the intent survives an addopts change.
echo "== L1/L2 unit + contract (assignment-a)"; "$PY" -m pytest assignment-a/tests -q -m "not live"
echo "== L1/L2 unit + contract (assignment-b)"; "$PY" -m pytest assignment-b/tests -q -m "not live"
echo "== L3 offline eval (tuned + held-out)";   "$PY" assignment-a/evals/run_eval.py --offline \
                                                     --questions questions held_out --out "$EVAL_OUT"
echo "== L4 demo-path";                        "$PY" -m pytest assignment-a/tests assignment-b/tests -q -m "demo and not live"
echo "ALL GATES GREEN"
