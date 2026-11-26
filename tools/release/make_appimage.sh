#!/usr/bin/env bash
# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
#
# make_appimage.sh KIT.tar.gz VERSION OUTDIR [CACHE]: the Linux kit of a release (tools/release/package.py) as one AppImage.
#
#   OrbitalsPCRecomp-<VERSION>-x86_64.AppImage
#     usr/kit/      the kit, unchanged (no game files, no game code: the player builds them from their own copy)
#     usr/python/   CPython with Tk (python-build-standalone), so the launcher needs no python3-tk
#     AppRun        copies the kit once into ${XDG_DATA_HOME:-~/.local/share}/OrbitalsPCRecomp/kit-<VERSION> (an AppImage is read-only;
#                   the game is compiled and installed beside the kit) and starts the launcher there with the bundled Python
#
# Still from the system, as with the tar.gz: gcc, SPIRV-Tools, the .NET 10 runtime (the launcher names the packages), a Vulkan driver.
# Every download is pinned and checked against its SHA-256 here; they are kept in CACHE (default: ./appimage-cache).
# Runs on any x86-64 Linux (WSL included) with bash, curl, tar, sha256sum; no FUSE needed (APPIMAGE_EXTRACT_AND_RUN).
set -euo pipefail
kit=${1:?kit tar.gz}; version=${2:?version}; out=${3:?output folder}; cache=${4:-appimage-cache}
kit=$(readlink -f "$kit"); mkdir -p "$out" "$cache"; out=$(readlink -f "$out"); cache=$(readlink -f "$cache")

PY_URL=https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.12.16+20261026-x86_64-unknown-linux-gnu-install_only.tar.gz
PY_SHA=6a79e922e50006b601f29e688407659da1c2b86ebcd4e9c7254cf234be8b89de
TOOL_URL=https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage
TOOL_SHA=ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0
RT_URL=https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64
RT_SHA=2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d

fetch() {   # url sha file: download once, refuse a file whose SHA-256 differs
  local f="$cache/$3"
  [[ -f "$f" ]] || curl -fsSL --retry 3 -o "$f.part" "$1" && { [[ -f "$f" ]] || mv "$f.part" "$f"; }
  echo "$2  $f" | sha256sum -c --quiet - || { echo "SHA-256 mismatch: $3 (removed)" >&2; rm -f "$f"; exit 1; }
}
fetch "$PY_URL" "$PY_SHA" python.tar.gz
fetch "$TOOL_URL" "$TOOL_SHA" appimagetool.AppImage
fetch "$RT_URL" "$RT_SHA" runtime-x86_64
chmod +x "$cache/appimagetool.AppImage"

work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
app="$work/OrbitalsPCRecomp.AppDir"; mkdir -p "$app/usr/kit" "$app/usr"
tar xzf "$kit" -C "$app/usr/kit" --strip-components=1
[[ -f "$app/usr/kit/launcher/__main__.py" && -f "$app/usr/kit/VERSION" ]] || { echo "not an Orbitals PC Recomp Linux kit: $kit" >&2; exit 1; }
[[ "$(tr -d '\r\n' < "$app/usr/kit/VERSION")" == "$version" ]] || { echo "the kit is not version $version" >&2; exit 1; }
tar xzf "$cache/python.tar.gz" -C "$app/usr"   # -> usr/python
"$app/usr/python/bin/python3" -c "import tkinter, sys; assert sys.version_info >= (3, 12)" 2>/dev/null \
  || echo "note: the bundled Python's Tk could not be checked here (no display or libX11): it is checked when the AppImage starts" >&2
rm -rf "$app/usr/python/lib/python3.12/test" "$app/usr/python/lib/python3.12/idlelib/idle_test"

cp "$app/usr/kit/launcher/assets/orbitals-icon.png" "$app/orbitals-pc-recomp.png"
cat > "$app/orbitals-pc-recomp.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Liftoff (Orbitals PC Recomp)
Comment=Install Orbitals from your own game files and play it natively
Exec=AppRun
Icon=orbitals-pc-recomp
Terminal=false
Categories=Game;
X-AppImage-Version=$version
EOF

cat > "$app/AppRun" <<'EOF'
#!/usr/bin/env bash
# Orbitals PC Recomp AppImage: the kit is copied once to a writable folder (the game is built and installed beside it), then the
# launcher starts there with the bundled Python. Nothing outside that folder is changed.
set -u
here="$(dirname "$(readlink -f "$0")")"
version="$(tr -d '\r\n' < "$here/usr/kit/VERSION")"
data="${XDG_DATA_HOME:-$HOME/.local/share}/OrbitalsPCRecomp"
kit="$data/kit-$version"
say() {
  if command -v kdialog >/dev/null 2>&1; then kdialog --title "Orbitals PC Recomp" --error "$1"
  elif command -v zenity >/dev/null 2>&1; then zenity --error --title="Orbitals PC Recomp" --width=480 --text="$1"
  else echo "$1" >&2; fi
}
if [[ "${RECOMPLAUNCHER:-}" == 1 && -w "$here/usr/kit" ]]; then
  # RecompLauncher unpacks the AppImage into a folder of its own and updates it there: the kit runs in place, nothing is copied, and
  # its setup and play (recomplauncher.json, launcher/recomplauncher.py) use the bundled Python, with no window
  kit="$here/usr/kit"
  case "${1:-}" in --prepare|--play) cd "$kit" && exec "$here/usr/python/bin/python3" -B -m launcher "$@" ;; esac
elif [[ ! -f "$kit/.complete" ]]; then
  mkdir -p "$data" && rm -rf "$kit.part" && cp -a "$here/usr/kit" "$kit.part" && rm -rf "$kit" && mv "$kit.part" "$kit" && touch "$kit/.complete" \
    || { say "Orbitals PC Recomp could not copy its files to $kit (disk full or not writable?)."; exit 1; }
fi
# The system's Python when it is 3.12+ with a Tk that draws scalable fonts (Xft): the bundled Tk (python-build-standalone) only has
# X11 core fonts, readable but plain and without Japanese. The bundled Python otherwise, so no python3-tk is needed.
py="$here/usr/python/bin/python3"
for c in python3.14 python3.13 python3.12 python3; do
  command -v "$c" >/dev/null 2>&1 || continue
  if timeout 15 "$c" -c "import sys, tkinter; assert sys.version_info >= (3, 12); r = tkinter.Tk(); r.withdraw(); f = r.tk.call('::tk::pkgconfig', 'get', 'fontsystem'); r.destroy(); sys.exit(0 if f == 'xft' else 1)" >/dev/null 2>&1; then
    py="$(command -v "$c")"; break
  fi
done
if ! "$py" -c "import tkinter; tkinter.Tcl()" >/dev/null 2>&1; then
  say "The launcher's window library (Tk) could not start. Install your distribution's libX11 and libXft packages (most desktops have them), then start Orbitals PC Recomp again."
  exit 1
fi
cd "$kit" || exit 1
mkdir -p "${XDG_STATE_HOME:-$HOME/.local/state}/orbitals-launcher"
export ORBITALS_APPIMAGE="${APPIMAGE:-}"
exec "$py" -B -m launcher "$@" 2>>"${XDG_STATE_HOME:-$HOME/.local/state}/orbitals-launcher/stderr.log"
EOF
chmod +x "$app/AppRun"

name="OrbitalsPCRecomp-$version-x86_64.AppImage"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$cache/appimagetool.AppImage" --no-appstream --runtime-file "$cache/runtime-x86_64" "$app" "$out/$name" >"$work/appimagetool.log" 2>&1 \
  || { cat "$work/appimagetool.log" >&2; exit 1; }
chmod +x "$out/$name"
echo "$out/$name ($(du -h "$out/$name" | cut -f1)); python 3.12.16 (python-build-standalone 20261026), appimagetool 1.9.1, runtime 20251108"
