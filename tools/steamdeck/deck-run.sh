#!/usr/bin/env bash
# Orbitals on the Steam Deck: one isolated, measured run (the Linux side of tools/claude_laptop/run-orbitals.ps1).
#
#   deck-run.sh TAG [options]
#     --base DIR        playable folder: Orbitals, Orbitals_code.so, Orbitals.ini, Orbitals.hints, Orbitals_nvn, Orbitals_data/save
#                       (default: <script dir>/..)
#     --data DIR        folder with exefs/ and romfs/ (default: <base>/Orbitals_data, else <base>/../Orbitals_data)
#     --seconds N       stop the game after N seconds (--seconds of the runtime)
#     --script S        scripted pad 1 (ms:hexmask[/ms],...)   --script2 S  scripted pad 2
#     --ini k=v         replace a key in the run's Orbitals.ini (repeatable)
#     --env K=V         extra environment variable (repeatable)
#     --args "..."      game arguments (default: --renderer=vulkan --fullscreen=1 --docked=0)
#     --shots A-B[/ms]  one window capture per ms (default 3000) between A and B seconds (repeatable)
#     --perf A-B        perf record (user space, 999 Hz, call graphs off) of the game between A and B seconds
#     --save DIR        the save copied into the run (default: <base>/Orbitals_data/save); the scripted paths need the test save
#     --overlay DIR     files served over the game's RomFS (Orbitals_data/romfs_overlay, e.g. Unreal's Saved/Config user layer)
#     --fresh-cache     copy Orbitals_nvn instead of sharing the base's (cold shader / pipeline cache measurements)
#     --unmute          sound on (default: SWR_AUDIO_MUTE=1, the mixer keeps running)
#     --runs DIR        where run folders go (default: <base>/../runs)
#     --gpu MODE        GPU clock policy for the run: auto, high or fixed:MHZ (gpu-clock.sh; restored when the run ends, even interrupted)
# Output: <runs>/<TAG>-<stamp>/ with run.txt, stdout.txt, frames.csv, telemetry.csv (1 Hz), frames/*.png, perf.data
set -uo pipefail

here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
tag="${1:?usage: deck-run.sh TAG [options]}"; shift
base="$here/.."; data=""; seconds=0; script=""; script2=""; ini=(); envs=(); shots=(); perfwin=""; overlay=""; save=""; fresh=0; unmute=0; runs=""
gargs="--renderer=vulkan --fullscreen=1 --docked=0"; gpu=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --base) base="$2"; shift 2;; --data) data="$2"; shift 2;; --seconds) seconds="$2"; shift 2;;
    --script) script="$2"; shift 2;; --script2) script2="$2"; shift 2;;
    --ini) ini+=("$2"); shift 2;; --env) envs+=("$2"); shift 2;; --args) gargs="$2"; shift 2;;
    --shots) shots+=("$2"); shift 2;; --perf) perfwin="$2"; shift 2;; --overlay) overlay="$(realpath "$2")"; shift 2;; --save) save="$(realpath "$2")"; shift 2;; --fresh-cache) fresh=1; shift;;
    --unmute) unmute=1; shift;; --runs) runs="$2"; shift 2;; --gpu) gpu="$2"; shift 2;;
    *) echo "unknown option $1" >&2; exit 2;;
  esac
done
base="$(realpath "$base")"
if [[ -z "$data" ]]; then if [[ -d "$base/Orbitals_data/romfs" ]]; then data="$base/Orbitals_data"; else data="$(realpath "$base/../Orbitals_data")"; fi; fi
data="$(realpath "$data")"
[[ -z "$runs" ]] && runs="$(realpath -m "$base/../runs")"
for p in "$base/Orbitals" "$base/Orbitals_code.so" "$base/Orbitals.ini" "$data/exefs" "$data/romfs"; do
  [[ -e "$p" ]] || { echo "missing: $p" >&2; exit 2; }
done
if pgrep -x Orbitals >/dev/null; then echo "an Orbitals instance is already running" >&2; exit 3; fi

run="$runs/$tag-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$run/Orbitals_data" "$run/frames" "$run/tmp"
# the runtime finds its files next to /proc/self/exe: the executable is copied, the rest linked
cp "$base/Orbitals" "$run/Orbitals"; ln -s "$base/Orbitals_code.so" "$run/Orbitals_code.so"
[[ -f "$base/Orbitals.hints" ]] && cp "$base/Orbitals.hints" "$run/"
ln -s "$data/exefs" "$run/Orbitals_data/exefs"; ln -s "$data/romfs" "$run/Orbitals_data/romfs"
cp -r "${save:-$base/Orbitals_data/save}" "$run/Orbitals_data/save"
[[ -n "$overlay" ]] && ln -s "$overlay" "$run/Orbitals_data/romfs_overlay"
if [[ $fresh == 1 ]]; then cp -r "$base/Orbitals_nvn" "$run/Orbitals_nvn"; else ln -s "$base/Orbitals_nvn" "$run/Orbitals_nvn"; fi
cp "$base/Orbitals.ini" "$run/Orbitals.ini"
for kv in "${ini[@]}"; do k="${kv%%=*}"; v="${kv#*=}"; if grep -q "^$k=" "$run/Orbitals.ini"; then sed -i "s|^$k=.*|$k=$v|" "$run/Orbitals.ini"; else echo "$k=$v" >> "$run/Orbitals.ini"; fi; done   # a key the base ini lacks is added

a="$gargs"
[[ $seconds -gt 0 ]] && a+=" --seconds=$seconds"
[[ -n "$script" ]] && a+=" --script=$script"
[[ -n "$script2" ]] && a+=" --script2=$script2"

# the desktop session's display (runs started over SSH draw on the Deck's screen)
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if [[ -z "${DISPLAY:-}" ]]; then export DISPLAY=:0; fi
if [[ -z "${XAUTHORITY:-}" ]]; then x="$(ls "$XDG_RUNTIME_DIR"/xauth_* 2>/dev/null | head -1)"; [[ -n "$x" ]] && export XAUTHORITY="$x"; fi
export SWR_GPU=nvn NXRT_GFX=vulkan TMPDIR="$run/tmp" NXRT_VK_SHOT_DIR="$run/frames"
[[ $unmute == 0 ]] && export SWR_AUDIO_MUTE=1
ctl="$run/shot-request.txt"
[[ ${#shots[@]} -gt 0 ]] && export NXRT_VK_SHOT_FILE="$ctl"
for kv in "${envs[@]}"; do export "$kv"; done

{
  echo "tag=$tag"; echo "started=$(date -Iseconds)"; echo "host=$(cat /etc/hostname) $(cat /sys/class/dmi/id/product_name 2>/dev/null) $(uname -r)"
  echo "os=$(. /etc/os-release; echo "$PRETTY_NAME $VERSION_ID")"
  echo "base=$base"; echo "data=$data"; echo "args=$a"; echo "ini=${ini[*]:-}"; echo "env=${envs[*]:-}"
  echo "shots=${shots[*]:-}"; echo "perf=$perfwin"; echo "overlay=$overlay"; echo "save=${save:-$base/Orbitals_data/save}"; echo "fresh_cache=$fresh"
  echo "module_sha=$(sha256sum "$base/Orbitals_code.so" | cut -c1-16) runtime_sha=$(sha256sum "$base/Orbitals" | cut -c1-16)"
  echo "power_supply=$(cat /sys/class/power_supply/ACAD/online 2>/dev/null) battery=$(cat /sys/class/power_supply/BAT1/capacity 2>/dev/null)%"
  echo "mesa=$(vulkaninfo --summary 2>/dev/null | grep -m1 driverInfo | sed 's/.*= //')"
} > "$run/run.txt"

hw() { for h in /sys/class/hwmon/hwmon*; do [[ "$(cat "$h/name")" == "$1" ]] && { echo "$h"; return; }; done; }
gpu_h="$(hw amdgpu)"; deck_h="$(hw steamdeck_hwmon)"; acpi_h="$(hw acpitz)"; dev=/sys/class/drm/card0/device

cd "$run"
# GPU clock policy: a save left by an interrupted run is restored first; this run's is restored when the script ends, however it ends
bash "$here/gpu-clock.sh" restore >> "$run/run.txt" 2>&1
if [[ -n "$gpu" ]]; then
  trap 'bash "$here/gpu-clock.sh" restore >> "$run/run.txt" 2>&1' EXIT
  trap 'exit 130' INT TERM
  if [[ "$gpu" == fixed:* ]]; then bash "$here/gpu-clock.sh" fixed "${gpu#fixed:}" >> "$run/run.txt" 2>&1 || { echo "gpu clock not applied" >&2; exit 4; }
  else bash "$here/gpu-clock.sh" "$gpu" >> "$run/run.txt" 2>&1 || { echo "gpu clock not applied" >&2; exit 4; }; fi
fi
echo "gpu=${gpu:-unchanged} $(bash "$here/gpu-clock.sh" show 2>&1)" >> "$run/run.txt"
t0=$(date +%s%3N)
# a Deck left alone between runs has its panel off (DPMS): FIFO presents would wait for it; turn it on first (no root needed)
WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}" kscreen-doctor --dpms on >/dev/null 2>&1 || true
sleep 1
echo "dpms=$(cat /sys/class/drm/card0-eDP-1/dpms 2>/dev/null)" >> "$run/run.txt"
# an unattended Deck turns its screen off after a few idle minutes, and FIFO presents then wait for it: keep it on during the run
inhibit=(); command -v kde-inhibit >/dev/null && inhibit=(kde-inhibit --power --screenSaver)
"${inhibit[@]}" ./Orbitals $a > "$run/stdout.txt" 2>&1 &
wpid=$!
# the game's own pid (under kde-inhibit when there is one): telemetry and perf follow it
pid=$wpid; for _ in $(seq 50); do g=$(pgrep -P $wpid -x Orbitals) && { pid=$g; break; }; [[ ${#inhibit[@]} -eq 0 ]] && break; sleep 0.1; done
echo "pid=$pid inhibit=${inhibit[*]:-none}" >> "$run/run.txt"

# 1 Hz telemetry: whole-machine CPU busy %, the game's CPU % (of one core) and threads, RSS, GPU busy %, sclk, APU power, temperatures, fan, VRAM / GTT
(
  echo "t,cpu_pct,game_cpu_pct,threads,rss_mb,gpu_busy,sclk_mhz,ppt_w,edge_c,acpi_c,fan_rpm,vram_mb,gtt_mb,bat_pct,bat_ua,gfx_mhz,cpu_mhz"
  read -r _ u n s i w q sq st _ < /proc/stat; pbusy=$((u+n+s+q+sq+st)); ptot=$((pbusy+i+w))
  pg=0; tk=$(getconf CLK_TCK)
  while kill -0 $pid 2>/dev/null; do
    sleep 1
    read -r _ u n s i w q sq st _ < /proc/stat; busy=$((u+n+s+q+sq+st)); tot=$((busy+i+w))
    cpu=$(( tot>ptot ? 100*(busy-pbusy)/(tot-ptot) : 0 )); pbusy=$busy; ptot=$tot
    if [[ -r /proc/$pid/stat ]]; then
      st_=( $(sed 's/.*) //' /proc/$pid/stat) ); g=$(( st_[11] + st_[12] )); gc=$(( (g-pg)*100/tk )); pg=$g; thr=${st_[17]}
      rss_kb=$(awk '/VmRSS/{print $2}' /proc/$pid/status 2>/dev/null); rss=$(( ${rss_kb:-0} / 1024 ))   # (empty while the game exits)
    else gc=0; thr=0; rss=0; fi
    sclk=$(awk '/\*/{gsub("Mhz","",$2); print $2}' $dev/pp_dpm_sclk 2>/dev/null)
    t=$(( $(date +%s%3N) - t0 ))
    echo "$t $cpu $gc $thr $rss $(cat $dev/gpu_busy_percent) ${sclk:-0} $(cat $gpu_h/power1_average) $(cat $gpu_h/temp1_input) $(cat $acpi_h/temp1_input 2>/dev/null || echo 0)" \
         "$(cat $deck_h/fan1_input 2>/dev/null || echo 0) $(( $(cat $dev/mem_info_vram_used)/1048576 )) $(( $(cat $dev/mem_info_gtt_used)/1048576 ))" \
         "$(cat /sys/class/power_supply/BAT1/capacity) $(cat /sys/class/power_supply/BAT1/current_now)" \
         "$(cat $gpu_h/freq1_input 2>/dev/null || echo 0) $(cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq 2>/dev/null | awk '{s+=$1;n++} END {print n ? int(s/n/1000) : 0}')" |
      awk '{printf "%.1f,%d,%d,%d,%d,%d,%d,%.2f,%.1f,%.1f,%d,%d,%d,%d,%d,%d,%d\n",$1/1000,$2,$3,$4,$5,$6,$7,$8/1e6,$9/1000,$10/1000,$11,$12,$13,$14,$15,$16/1e6,$17}'
  done
) > "$run/telemetry.csv" &
tele=$!

# window captures (the runtime takes one at the next present when the control file exists, then deletes it)
if [[ ${#shots[@]} -gt 0 ]]; then
  ( last=-1000000
    while kill -0 $pid 2>/dev/null; do
      now=$(( $(date +%s%3N) - t0 ))
      for w in "${shots[@]}"; do r="${w%%/*}"; st=3000; [[ "$w" == */* ]] && st="${w#*/}"
        a0=$(( ${r%%-*} * 1000 )); a1=$(( ${r#*-} * 1000 ))
        if (( now >= a0 && now <= a1 && now - last >= st )) && [[ ! -e "$ctl" ]]; then : > "$ctl"; last=$now; fi
      done
      sleep 0.05
    done ) &
fi

if [[ -n "$perfwin" ]]; then
  ( p0=${perfwin%%-*}; p1=${perfwin#*-}
    while kill -0 $pid 2>/dev/null && (( $(date +%s%3N) - t0 < p0*1000 )); do sleep 0.2; done
    kill -0 $pid 2>/dev/null && timeout -s INT $((p1-p0)) perf record -F 499 -m 8 -e cpu-clock:u -p $pid -o "$run/perf.data" > "$run/perf.log" 2>&1 ) &
fi

wait $wpid; code=$?
t=$(awk -v d=$(( $(date +%s%3N) - t0 )) 'BEGIN{printf "%.1f", d/1000}')
wait $tele 2>/dev/null
echo "exit=$code seconds=$t" >> "$run/run.txt"
rm -rf "$run/tmp"
echo "run=$run exit=$code seconds=$t"
