#!/usr/bin/env bash
# Orbitals on the Steam Deck (SteamOS game mode or desktop mode), from the folder this script is in, e.g. /home/deck/Downloads/Orbital:
#   Orbitals  Orbitals_code.so  Orbitals.ini  Orbitals.hints  Orbitals_nvn/  Orbitals_data/{exefs,romfs,save}
# Game mode: add this script as a non-Steam game (Steam > Add a Game > Add a Non-Steam Game), then play with the Deck's controls.
# Desktop mode: run it from a terminal or Dolphin. Nothing outside this folder is changed; SteamOS stays read-only.
set -u
here="$(cd -- "$(dirname -- "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
cd "$here" || exit 1
for f in Orbitals Orbitals_code.so Orbitals_data/exefs Orbitals_data/romfs; do
  [[ -e "$f" ]] || { echo "Orbitals: $here/$f is missing" >&2; exit 2; }
done
[[ -x Orbitals ]] || chmod +x Orbitals
export SWR_GPU=nvn NXRT_GFX=vulkan
# Dispatch write-backs compared on the GPU (STEAM_DECK_PERFORMANCE.md: +4.9 % in co-op on the Deck, 534,027 ranges checked against
# the CPU's comparison with 0 differences); NXRT_VK_WB_GPU=0 goes back to the CPU comparison
export NXRT_VK_WB_GPU="${NXRT_VK_WB_GPU:-1}"
# The flight recorder (F5 captures of the last frames) is a development tool: ~440 MB of memory and a frame copy each present. NXRT_VK_FLIGHT=1 keeps it
export NXRT_VK_FLIGHT="${NXRT_VK_FLIGHT:-0}"
# GPU clock (STEAM_DECK_PERFORMANCE.md 4.8): a fixed 1100 MHz measured +3.6 % FPS and -11 % p95 frame time in co-op against the
# driver's automatic policy (the 15 W limit is the firmware's and stays; higher clocks take power from the CPU and were slower).
# Set through SteamOS' own helper (the quick access menu's manual GPU clock), restored when the game ends; a state left by a crash is
# restored first. ORBITALS_GPU_CLOCK=auto leaves the clock alone
gpu="${ORBITALS_GPU_CLOCK:-1100}"
gpu_restore() { :; }   # no-op unless a clock was set below
if [[ "$gpu" != auto && -f "$here/gpu-clock.sh" ]]; then
  bash "$here/gpu-clock.sh" restore >/dev/null 2>&1   # clear a state a previous crash may have left
  if bash "$here/gpu-clock.sh" fixed "$gpu" >/dev/null 2>&1; then
    gpu_restore() { bash "$here/gpu-clock.sh" restore >/dev/null 2>&1; }
  fi
fi
# One EXIT handler restores the clock and stops the game however this script ends: a normal quit, or a TERM / INT from Steam
# (game mode's Stop) or the terminal. TERM / INT just exit, which runs the EXIT handler; the game is killed there, not before,
# so the clock is always put back. A hard kill of this script (SIGKILL) or a power loss cannot run it -- the next launch's
# restore above clears that. Steam's shader pre-caching and overlay stay usable; the runtime keeps its cache in Orbitals_nvn/vk.
pid=
cleanup() { [[ -n "$pid" ]] && kill -TERM "$pid" 2>/dev/null; gpu_restore; }
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
./Orbitals --renderer=vulkan "$@" &
pid=$!
wait "$pid"
