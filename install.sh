#!/usr/bin/env bash
# Lumode installer — sets up lumode in ~/.local/bin
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"

echo "Lumode installer"
echo "================"
echo

# ── Python check ─────────────────────────────────────────────────────────────
PYTHON=$(command -v python3 2>/dev/null || true)
if [[ -z "$PYTHON" ]]; then
    echo "Error: python3 not found. Please install Python 3.9+." >&2
    exit 1
fi
PY_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Python $PY_VER found at $PYTHON"

# ── Dependency installation ───────────────────────────────────────────────────
echo
echo "Installing dependencies..."

install_pkg() {
    local pkg="$1"
    local apt_pkg="$2"

    if "$PYTHON" -c "import $pkg" 2>/dev/null; then
        echo "  $pkg: already installed"
        return
    fi

    # Try apt first (Debian/Ubuntu), then pip
    if command -v apt-get &>/dev/null && apt-cache show "$apt_pkg" &>/dev/null; then
        echo "  $pkg: installing via apt..."
        sudo apt-get install -y -q "$apt_pkg"
    elif "$PYTHON" -m pip install --quiet --user "$pkg" 2>/dev/null; then
        echo "  $pkg: installed via pip"
    else
        echo "  Warning: could not install $pkg — continuing anyway"
    fi
}

install_pkg requests       python3-requests
install_pkg rich           python3-rich
install_pkg prompt_toolkit python3-prompt-toolkit

# ── ~/.local/bin setup ───────────────────────────────────────────────────────
echo
echo "Setting up ~/.local/bin..."
mkdir -p "$BIN_DIR"

chmod +x "$SCRIPT_DIR/lumode"
chmod +x "$SCRIPT_DIR/lumo_cli.py"
ln -sf "$SCRIPT_DIR/lumode" "$BIN_DIR/lumode"
ln -sf "$SCRIPT_DIR/lumo_cli.py" "$BIN_DIR/lumo"
ln -sf "$SCRIPT_DIR/lumo_cli.py" "$BIN_DIR/lumo-cli"
echo "  Linked: lumode -> $SCRIPT_DIR/lumode"
echo "  Linked: lumo    -> $SCRIPT_DIR/lumo_cli.py"
echo "  Linked: lumo-cli -> $SCRIPT_DIR/lumo_cli.py"

# ── PATH check ───────────────────────────────────────────────────────────────
echo
if [[ ":$PATH:" == *":$BIN_DIR:"* ]]; then
    echo "~/.local/bin is already in PATH."
else
    echo "Note: ~/.local/bin is not in PATH."
    SHELL_NAME="$(basename "${SHELL:-bash}")"
    RC_FILE="$HOME/.${SHELL_NAME}rc"
    echo "Add this to $RC_FILE:"
    echo
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo
    echo "Then run:  source $RC_FILE"
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo
echo "Done! Run: lumode"
echo
echo "First-time setup:"
echo "  1. Log into https://lumo.proton.me in Firefox"
echo "  2. Run: lumode"
echo
echo "Or export credentials directly:"
echo "  export LUMO_UID=<your-uid>"
echo "  export LUMO_TOKEN=<your-access-token>"
