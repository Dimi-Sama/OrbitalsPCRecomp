#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
    echo "Usage: bash tools/build-orbitals-linux.sh GAME_DATA OUT_DIR [JOBS]" >&2
    exit 2
fi

game_data="$(realpath -- "$1")"
out_dir="$(realpath -m "$2")"
jobs="${3:-$(nproc)}"
python="${ORBITALS_PYTHON:-python3}"
echo '[1/5] Checking the Linux build tools and your game files'
if [[ ! -f "$game_data/exefs/main" || ! -f "$game_data/exefs/main.npdm" || ! -d "$game_data/romfs" ]]; then
    echo "GAME_DATA must contain exefs/main, exefs/main.npdm and romfs/ from your local copy." >&2
    exit 2
fi
if ! command -v "$python" >/dev/null || ! command -v gcc >/dev/null; then
    echo 'Python 3 and GCC are required. See BUILDING.md.' >&2
    exit 2
fi

repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"
echo '[2/5] Preparing the links to your game data'
data_dir="$out_dir/Orbitals_data"
mkdir -p -- "$data_dir"
for name in exefs romfs; do
    target="$data_dir/$name"
    source="$(realpath -- "$game_data/$name")"
    if [[ -L "$target" ]]; then
        if [[ "$(realpath -- "$target")" != "$source" ]]; then
            echo "$target points to a different copy. Choose a fresh installation folder." >&2
            exit 2
        fi
    elif [[ ! -e "$target" ]]; then
        ln -s -- "$source" "$target"
    fi
done

runtime="$repo/bin/runtime_linux_x11"
if [[ -x "$runtime" ]]; then
    echo '[3/5] Using the Linux runtime included in the archive'
else
    echo '[3/5] Building the Vulkan layer and Linux runtime'
    "$python" -B tools/build_nvn.py --linux --jobs "$jobs"
    "$python" -B switchrecomp.py --build-runtime --target linux --backend x11 --cc gcc
fi

echo '[4/5] Recompiling your copy of Orbitals'
"$python" -B switchrecomp.py "$game_data" --out Orbitals --outdir "$out_dir" \
    --runtime "$runtime" --target linux --backend x11 --cc gcc --jobs "$jobs"
echo "[5/5] Ready to play from $out_dir"
