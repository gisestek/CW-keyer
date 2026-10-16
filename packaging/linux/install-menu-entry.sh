#!/usr/bin/env bash
# Adds CW Station to the desktop's application menu (for this user only).
# Run it from the unpacked CWStation folder:   ./install-menu-entry.sh
# Remove again:                                ./install-menu-entry.sh --remove
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ENTRY="$APPS/cwstation.desktop"

if [ "${1:-}" = "--remove" ]; then
    rm -f "$ENTRY"
    echo "Removed $ENTRY"
    exit 0
fi

mkdir -p "$APPS"
cat > "$ENTRY" <<EOF
[Desktop Entry]
Type=Application
Name=CW Station
Comment=Decode and send CW (Morse) with your radio
Exec="$DIR/CWStation"
Path=$DIR
Terminal=false
Categories=HamRadio;Network;
Keywords=CW;Morse;ham;radio;
EOF
chmod +x "$ENTRY"
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" >/dev/null 2>&1 || true
echo "Added CW Station to the application menu ($ENTRY)."

if ! ldconfig -p 2>/dev/null | grep -q libportaudio.so.2; then
    echo "Note: audio input needs PortAudio:  sudo apt install libportaudio2"
fi
if ! id -nG | grep -qw dialout; then
    echo "Note: for a WinKeyer on a USB serial port, add yourself to the dialout group:"
    echo "      sudo usermod -aG dialout $USER   (then log out and in again)"
fi
