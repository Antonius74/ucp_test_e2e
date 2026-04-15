#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$ROOT_DIR/a2a/business_agent/.venv/bin/python"

section() {
  echo
  echo "============================================================"
  echo "$1"
  echo "============================================================"
}

fail() {
  echo "ERROR: $1" >&2
  exit 1
}

if [[ ! -x "$VENV_PYTHON" ]]; then
  fail "Python venv not found at $VENV_PYTHON. Create it first in a2a/business_agent."
fi

section "1) A2A Business Agent E2E tests"
(
  cd "$ROOT_DIR/a2a/business_agent"
  TEST_BACKEND_PORT="${A2A_BACKEND_TEST_PORT:-11999}"
  TEST_PROFILE_PORT="${A2A_PROFILE_TEST_PORT:-13001}"
  A2A_BACKEND_TEST_PORT="$TEST_BACKEND_PORT" \
    A2A_PROFILE_TEST_PORT="$TEST_PROFILE_PORT" \
    "$VENV_PYTHON" -m unittest -v tests/test_a2a_e2e.py
)

section "2) REST Python server integration tests"
(
  cd "$ROOT_DIR/rest/python/server"
  # NOTE: integration_test.py uses absl flags; run as script (not unittest module).
  "$VENV_PYTHON" integration_test.py
)

section "3) Chat client production build"
(
  cd "$ROOT_DIR/a2a/chat-client"
  PATH="/opt/homebrew/bin:/usr/local/bin:$PATH" /opt/homebrew/bin/npm run build
)

section "All checks passed"
echo "Everything completed successfully."
