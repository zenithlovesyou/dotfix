#!/usr/bin/env bash
# dotfix installer
set -euo pipefail

REPO="https://raw.githubusercontent.com/iamzephlol/dotfix/main/dotfix.py"
BIN_DIR="${DOTFIX_BIN_DIR:-$HOME/.local/bin}"

info()  { printf '\033[0;36m::\033[0m %s\n' "$1"; }
ok()    { printf '\033[0;32m✓\033[0m %s\n' "$1"; }
fail()  { printf '\033[0;31m✗\033[0m %s\n' "$1" >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || fail "python3 is required"

mkdir -p "$BIN_DIR"

info "Downloading dotfix..."
if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$REPO" -o "$BIN_DIR/dotfix" || fail "download failed"
elif command -v wget >/dev/null 2>&1; then
    wget -qO "$BIN_DIR/dotfix" "$REPO" || fail "download failed"
else
    fail "need curl or wget"
fi

chmod +x "$BIN_DIR/dotfix"
ok "Installed to $BIN_DIR/dotfix"

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        info "Adding $BIN_DIR to PATH..."
        for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.config/fish/config.fish"; do
            [ -f "$rc" ] || continue
            grep -qF "$BIN_DIR" "$rc" && continue
            if [[ "$rc" == *fish* ]]; then
                printf 'fish_add_path %s\n' "$BIN_DIR" >> "$rc"
            else
                printf '\nexport PATH="%s:$PATH"\n' "$BIN_DIR" >> "$rc"
            fi
            ok "Updated $rc"
        done
        ;;
esac

ok "Done. Run 'dotfix init' to get started."
