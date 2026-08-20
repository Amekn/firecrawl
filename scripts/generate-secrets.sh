#!/usr/bin/env bash
set -euo pipefail
umask 077
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
TARGET_ROOT="${FIRECRAWL_ROOT:-$REPO_ROOT}"
install -d -m 700 "$TARGET_ROOT/secrets"
[[ -f "$TARGET_ROOT/.env" ]] || install -m 600 "$REPO_ROOT/.env.example" "$TARGET_ROOT/.env"
python3 - "$TARGET_ROOT" <<'PY'
from pathlib import Path
import secrets, sys
root = Path(sys.argv[1])
for path, key in (
    (root / "secrets/api.env", "FIRECRAWL_API_KEY"),
    (root / "secrets/stack.env", "POSTGRES_PASSWORD"),
):
    if not path.exists():
        path.write_text(f"{key}={secrets.token_hex(32)}\n")
    path.chmod(0o600)
PY
