#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/bberka/xpak.git"
INSTALL_DIR="$HOME/.local/lib/xpak"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
LAUNCHER="$BIN_DIR/xpak"
DESKTOP_FILE="$DESKTOP_DIR/xpak.desktop"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

info()    { echo -e "${CYAN}[xpak]${NC} $*"; }
success() { echo -e "${GREEN}[xpak]${NC} $*"; }
warn()    { echo -e "${YELLOW}[xpak]${NC} $*"; }
error()   { echo -e "${RED}[xpak]${NC} $*" >&2; }

# ── Dependency checks ──────────────────────────────────────────────────────────

info "Checking dependencies..."

if ! command -v git &>/dev/null; then
    error "git is not installed. Install it with: sudo pacman -S git"
    exit 1
fi

if ! command -v python3 &>/dev/null; then
    error "python3 is not installed. Install it with: sudo pacman -S python"
    exit 1
fi

if ! python3 -c "import PyQt6" &>/dev/null 2>&1; then
    warn "python-pyqt6 not found. Installing via pacman..."
    sudo pacman -S --needed python-pyqt6
fi

success "Dependencies OK"

# ── Clone or update ────────────────────────────────────────────────────────────

if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing installation at $INSTALL_DIR..."
    git -C "$INSTALL_DIR" pull --ff-only
    success "Updated to latest version"
else
    info "Cloning xpak to $INSTALL_DIR..."
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone "$REPO_URL" "$INSTALL_DIR"
    success "Cloned successfully"
fi

# ── Create launcher script ─────────────────────────────────────────────────────

mkdir -p "$BIN_DIR"

cat > "$LAUNCHER" << 'LAUNCHER_EOF'
#!/usr/bin/env bash
exec python3 "$HOME/.local/lib/xpak/xpak.py" "$@"
LAUNCHER_EOF

chmod +x "$LAUNCHER"
success "Launcher created at $LAUNCHER"

# ── Create .desktop file ───────────────────────────────────────────────────────

mkdir -p "$DESKTOP_DIR"
ICON_FILE="$INSTALL_DIR/assets/xpak.svg"

cat > "$DESKTOP_FILE" << DESKTOP_EOF
[Desktop Entry]
Name=XPAK
Comment=GUI Package Manager for Arch Linux / CachyOS
Exec=$LAUNCHER
Icon=$ICON_FILE
Terminal=false
Type=Application
Categories=System;PackageManager;
Keywords=package;manager;pacman;aur;flatpak;arch;
StartupWMClass=xpak
StartupNotify=true
DESKTOP_EOF

success ".desktop file created at $DESKTOP_FILE"

# ── Update desktop database ────────────────────────────────────────────────────

if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
fi

# ── PATH check ─────────────────────────────────────────────────────────────────

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    warn "~/.local/bin is not in your PATH."
    warn "Add the following to your ~/.bashrc or ~/.zshrc or ~/.config/fish/config.fish:"
    warn ""
    warn "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    warn ""
    warn "Then reload your shell or run: source ~/.bashrc"
fi

# ── Done ───────────────────────────────────────────────────────────────────────

echo ""
success "XPAK installed successfully!"
echo -e "${CYAN}  Run:${NC} xpak"
echo -e "${CYAN}  Or find it in your application launcher (KDE Plasma, GNOME, etc.)${NC}"
echo ""
