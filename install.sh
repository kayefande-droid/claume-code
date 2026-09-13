#!/usr/bin/env bash
# claume-code installer for Linux + macOS (+ WSL)
# Usage:  bash install.sh
# or:     curl -fsSL https://raw.githubusercontent.com/kayefande-droid/claume-code/main/install.sh | bash
set -euo pipefail

BANNER='
  _____ __ _ _____ _  _ ___ ___  _  _ ___
 / __) \ / / __) \ / )\ ) )_ \ / )( \ __)
( (__ ) X ( __ )) X ( | | | | | | ) ) __)
 \___)_(_)_(___/)_(_)_(_)_| |_(_/ (_(__(/

      pixel-grade CLI coding agent  -  free via NVIDIA NIM
'
printf '%s\n' "$BANNER"

# ---------------------------------------------------------------- paths
INSTALL_ROOT="$HOME/.claume"
APP_DIR="$INSTALL_ROOT/app"
VENV_DIR="$INSTALL_ROOT/venv"
BIN_DIR="$INSTALL_ROOT/bin"

echo "* install location: $INSTALL_ROOT"

# ---------------------------------------------------------------- python
PYTHON_CMD=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then
    ver="$("$cand" --version 2>/dev/null || true)"
    if [ -n "$ver" ]; then
      PYTHON_CMD="$cand"
      break
    fi
  fi
done
if [ -z "$PYTHON_CMD" ]; then
  echo "X Python 3 not found. Install Python 3.10+ first (apt install python3 / brew install python)." >&2
  exit 1
fi
echo "* found $("$PYTHON_CMD" --version)"

# ---------------------------------------------------------------- fetch app
SRC_ROOT=""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$SCRIPT_DIR" ] && [ -d "$SCRIPT_DIR/claume" ]; then
  SRC_ROOT="$SCRIPT_DIR"
else
  echo "* fetching claume-code from GitHub..."
  TMP_EXTRACT="$(mktemp -d)"
  ZIP="$TMP_EXTRACT/claume-code.zip"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "https://github.com/kayefande-droid/claume-code/archive/refs/heads/main.zip" -o "$ZIP"
  else
    wget -qO "$ZIP" "https://github.com/kayefande-droid/claume-code/archive/refs/heads/main.zip"
  fi
  unzip -q "$ZIP" -d "$TMP_EXTRACT"
  SRC_ROOT="$TMP_EXTRACT/claume-code-main"
fi
if [ ! -d "$SRC_ROOT/claume" ]; then
  echo "X could not locate the 'claume' package (looked in $SRC_ROOT)." >&2
  exit 1
fi

# fresh copy every run (idempotent reinstalls)
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR"
cp -R "$SRC_ROOT/claume" "$APP_DIR/"
for f in pyproject.toml README.md LICENSE; do
  [ -f "$SRC_ROOT/$f" ] && cp "$SRC_ROOT/$f" "$APP_DIR/"
done
# bundled skills (ui-ux-pro-max design pack) seed on first run
if [ -d "$SRC_ROOT/skills" ]; then
  cp -R "$SRC_ROOT/skills" "$APP_DIR/"
  echo "[OK] bundled skills staged (ui-ux-pro-max)"
fi
echo "[OK] copied agent core"

# ---------------------------------------------------------------- venv + deps
if [ ! -d "$VENV_DIR" ]; then
  echo "* creating virtual environment..."
  "$PYTHON_CMD" -m venv "$VENV_DIR"
fi
PY_BIN="$VENV_DIR/bin/python"
"$PY_BIN" -m pip install --quiet --upgrade pip
"$PY_BIN" -m pip install --quiet "$APP_DIR"
echo "[OK] dependencies installed (stdlib-only - nothing heavy)"

# ---------------------------------------------------------------- shim
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/claume" <<EOF
#!/usr/bin/env bash
exec "$PY_BIN" -m claume.cli "\$@"
EOF
chmod +x "$BIN_DIR/claume"
echo "[OK] created 'claume' command shim"

# ---------------------------------------------------------------- PATH
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;                      # already on PATH
  *)
    line='export PATH="$HOME/.claume/bin:$PATH"'
    added=0
    for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
      if [ -f "$rc" ] && ! grep -q '.claume/bin' "$rc" 2>/dev/null; then
        printf '\n%s\n' "$line" >> "$rc"
        added=1
      elif [ ! -f "$rc" ] && [ "$(basename "$SHELL")" = "$(basename "$rc" | sed 's/^\.//')" ]; then
        printf '%s\n' "$line" > "$rc"
        added=1
      fi
    done
    if [ "$added" = "1" ]; then
      echo "[OK] added $BIN_DIR to PATH (restart your shell or: source ~/.bashrc)"
    fi
    ;;
esac

# ---------------------------------------------------------------- done
echo
echo "  +----------------------------------------------+"
echo "  |  claume-code installed                       |"
echo "  |  open a NEW terminal tab and run:            |"
echo "  |                                              |"
echo "  |       claume                                 |"
echo "  |                                              |"
echo "  +----------------------------------------------+"
echo
echo "  first run asks for your free NVIDIA API key (build.nvidia.com)"
echo