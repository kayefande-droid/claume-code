#!/usr/bin/env bash
# claume-code updater (Linux / macOS / WSL)
# Pulls the latest main from GitHub and reinstalls - run after every git push.
# Usage:  bash update.sh
# or:     curl -fsSL https://raw.githubusercontent.com/kayefande-droid/claume-code/main/update.sh | bash
set -e

INSTALL_ROOT="$HOME/.claume"
REPO_DIR="$INSTALL_ROOT/repo"
VENV_DIR="$INSTALL_ROOT/venv"
SRC_ROOT=""

echo "* updating claume-code..."

# ---------------------------------------------------------------- source
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$SCRIPT_DIR" ] && [ -d "$SCRIPT_DIR/claume" ]; then
    # running from a repo checkout - just git pull it
    SRC_ROOT="$SCRIPT_DIR"
    git -C "$SRC_ROOT" fetch origin
    git -C "$SRC_ROOT" reset --hard origin/main >/dev/null
else
    if [ -d "$REPO_DIR/.git" ]; then
        git -C "$REPO_DIR" fetch origin
        git -C "$REPO_DIR" reset --hard origin/main >/dev/null
    else
        mkdir -p "$INSTALL_ROOT"
        git clone --depth=1 https://github.com/kayefande-droid/claume-code.git "$REPO_DIR"
    fi
    SRC_ROOT="$REPO_DIR"
fi

echo "* source at $SRC_ROOT (commit $(git -C "$SRC_ROOT" rev-parse --short HEAD))"

# ---------------------------------------------------------------- venv + reinstall
if [ ! -d "$VENV_DIR" ]; then
    PYTHON_CMD="${PYTHON_CMD:-python3}"
    command -v "$PYTHON_CMD" >/dev/null 2>&1 || PYTHON_CMD=python
    "$PYTHON_CMD" -m venv "$VENV_DIR"
fi
PY_BIN="$VENV_DIR/bin/python"
"$PY_BIN" -m pip install --quiet --upgrade pip
"$PY_BIN" -m pip install --quiet --force-reinstall --no-deps --no-cache-dir "$SRC_ROOT"
echo "[OK] $("$PY_BIN" -m pip show claume-code 2>/dev/null | grep '^Version' | tr -d '\r') installed (latest main)"

# keep the app dir fresh too (bundled skills etc.)
rm -rf "$INSTALL_ROOT/app"
mkdir -p "$INSTALL_ROOT/app"
cp -r "$SRC_ROOT/claume" "$INSTALL_ROOT/app/"
for f in pyproject.toml README.md; do
    [ -f "$SRC_ROOT/$f" ] && cp "$SRC_ROOT/$f" "$INSTALL_ROOT/app/"
done
[ -d "$SRC_ROOT/skills" ] && cp -r "$SRC_ROOT/skills" "$INSTALL_ROOT/app/"

echo ""
echo "  update complete - run:  claume"
