#!/usr/bin/env bash
# Orbitals PC Recomp launcher for Linux (launcher/README.md): double-click it in the file manager (or Orbitals-Launcher.desktop), no
# terminal needed. It needs Python 3.12+ with Tk; when that is missing it says which packages to install in a window (kdialog, zenity
# or a notification), not in a terminal. Nothing is installed by this script. ./Orbitals-Launcher.sh --menu adds an entry to the
# application menu (~/.local/share/applications), after asking.
here="$(cd -- "$(dirname -- "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
cd "$here" || exit 1

say() {   # a message in a window when there is no terminal
  if command -v kdialog >/dev/null 2>&1; then kdialog --title "Orbitals PC Recomp" --error "$1"
  elif command -v zenity >/dev/null 2>&1; then zenity --error --title="Orbitals PC Recomp" --width=480 --text="$1"
  elif command -v notify-send >/dev/null 2>&1; then notify-send "Orbitals PC Recomp" "$1"
  else echo "$1" >&2; fi
}
ask() {
  if command -v kdialog >/dev/null 2>&1; then kdialog --title "Orbitals PC Recomp" --yesno "$1"
  elif command -v zenity >/dev/null 2>&1; then zenity --question --title="Orbitals PC Recomp" --width=480 --text="$1"
  else return 1; fi
}

if [[ "${1:-}" == "--menu" ]]; then
  target="${XDG_DATA_HOME:-$HOME/.local/share}/applications/orbitals-pc-recomp.desktop"
  if ask "Add Orbitals PC Recomp to the application menu?

$target
(it starts $here/Orbitals-Launcher.sh)"; then
    mkdir -p "$(dirname "$target")"
    cat > "$target" <<EOF
[Desktop Entry]
Type=Application
Name=Orbitals PC Recomp
Comment=Launcher: install from your own game files, profiles, graphics settings, bug reports
Exec="$here/Orbitals-Launcher.sh"
Path=$here
Icon=$here/launcher/assets/orbitals-icon.png
Terminal=false
Categories=Game;
EOF
    chmod +x "$target"
  fi
  exit 0
fi

py=""
for c in python3.14 python3.13 python3.12 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1; then
    py="$c"; break
  fi
done
if [[ -z "$py" ]]; then
  say "The launcher needs Python 3.12 or newer with Tk.

Arch / CachyOS:   sudo pacman -S python tk
Debian / Ubuntu:  sudo apt install python3 python3-tk
Fedora:           sudo dnf install python3 python3-tkinter

Then open Orbitals-Launcher again."
  exit 1
fi
mkdir -p "${XDG_STATE_HOME:-$HOME/.local/state}/orbitals-launcher"
exec "$py" -B -m launcher "$@" 2>>"${XDG_STATE_HOME:-$HOME/.local/state}/orbitals-launcher/stderr.log"
