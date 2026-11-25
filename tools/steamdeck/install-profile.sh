#!/usr/bin/env bash
# install-profile.sh GAME_DIR [PROFILE]: writes a profile's keys (tools/steamdeck/profiles/<PROFILE>/profile.ini) into GAME_DIR/Orbitals.ini
# and puts orbitals-deck.sh next to the game. Default profile: steam_deck_720p30. Keeps a copy of the former ini as Orbitals.ini.bak
set -euo pipefail
here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
dir="$(realpath "$1")"; prof="${2:-steam_deck_720p30}"; src="$here/profiles/$prof/profile.ini"
[[ -f "$src" ]] || { echo "no profile $prof" >&2; exit 2; }
[[ -f "$dir/Orbitals.ini" ]] || { echo "no $dir/Orbitals.ini" >&2; exit 2; }
cp "$dir/Orbitals.ini" "$dir/Orbitals.ini.bak"
grep -E '^[a-z_]+=' "$src" | while IFS='=' read -r k v; do
  if grep -q "^$k=" "$dir/Orbitals.ini"; then sed -i "s|^$k=.*|$k=$v|" "$dir/Orbitals.ini"; else printf '%s=%s\n' "$k" "$v" >> "$dir/Orbitals.ini"; fi
done
install -m 755 "$here/orbitals-deck.sh" "$dir/orbitals-deck.sh"
echo "profile $prof written to $dir/Orbitals.ini; start with $dir/orbitals-deck.sh"
