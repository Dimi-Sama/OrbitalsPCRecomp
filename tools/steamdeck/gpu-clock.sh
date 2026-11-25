#!/usr/bin/env bash
# gpu-clock.sh: the Steam Deck GPU clock policy for a measurement, through SteamOS' own helper (steamos-priv-write: polkit allows it
# without a password, and it writes only its allow-list, the files the quick access menu's "manual GPU clock" writes). No overclocking
# (only values inside the driver's OD_RANGE), no voltage, no power cap change (the 15 W slowPPT / fastPPT stay as they are).
#
#   gpu-clock.sh show                 the policy, the OD clocks and the measured clock
#   gpu-clock.sh save                 keep the current state in $STATE (once: an existing save is the one to come back to)
#   gpu-clock.sh auto | high          the driver's policy (save first)
#   gpu-clock.sh fixed MHZ            manual, min = max = MHZ (inside OD_RANGE; save first)
#   gpu-clock.sh restore              back to the saved state, then forget it (a leftover save after a crash is restored the same way)
set -uo pipefail
STATE="${GPU_CLOCK_STATE:-$HOME/.cache/orbitals-gpu-clock.saved}"
PRIV=/usr/bin/steamos-polkit-helpers/steamos-priv-write
D=""; for c in /sys/class/drm/card*/device; do [[ -f $c/pp_od_clk_voltage && -f $c/power_dpm_force_performance_level ]] && grep -q DRIVER=amdgpu $c/uevent && { D=$c; break; }; done
[[ -n "$D" ]] || { echo "gpu-clock: no amdgpu device with OD clocks" >&2; exit 2; }
H=$(ls -d $D/hwmon/hwmon* 2>/dev/null | head -1)
w() { "$PRIV" "$1" "$2" >/dev/null 2>&1 || { echo "gpu-clock: write refused: $2 -> $1" >&2; return 1; }; }
od() { awk -v k="$1" '/^OD_SCLK:/{s=1;next} /^[A-Z_]+:/{s=0} s && $1==k":" {gsub("Mhz","",$2); print $2}' $D/pp_od_clk_voltage; }
range() { awk '/^SCLK:/{gsub("Mhz","",$2); gsub("Mhz","",$3); print $2, $3}' $D/pp_od_clk_voltage; }
measured() { [[ -n "$H" && -f $H/freq1_input ]] && echo $(( $(cat $H/freq1_input) / 1000000 )) || echo "?"; }
show() { echo "device $D: policy $(cat $D/power_dpm_force_performance_level), OD_SCLK $(od 0)-$(od 1) MHz, range $(range), measured $(measured) MHz, busy $(cat $D/gpu_busy_percent)%"; }
save() { [[ -f "$STATE" ]] && return 0; mkdir -p "$(dirname "$STATE")"; printf '%s %s %s\n' "$(cat $D/power_dpm_force_performance_level)" "$(od 0)" "$(od 1)" > "$STATE"; }
restore() {
    [[ -f "$STATE" ]] || return 0
    read -r lvl lo hi < "$STATE"
    if [[ "$lvl" == manual ]]; then w $D/power_dpm_force_performance_level manual && w $D/pp_od_clk_voltage "s 0 $lo" && w $D/pp_od_clk_voltage "s 1 $hi" && w $D/pp_od_clk_voltage c
    else   # the OD clocks back to what they were (the full range by default), then the policy
        w $D/power_dpm_force_performance_level manual && w $D/pp_od_clk_voltage "s 0 $lo" && w $D/pp_od_clk_voltage "s 1 $hi" && w $D/pp_od_clk_voltage c
        w $D/power_dpm_force_performance_level "$lvl"; fi
    [[ "$(cat $D/power_dpm_force_performance_level)" == "$lvl" ]] && rm -f "$STATE" && echo "gpu-clock: restored ($lvl, $lo-$hi MHz)"
}
case "${1:-show}" in
    show) show;;
    save) save;;
    restore) restore;;
    auto|high) save && w $D/power_dpm_force_performance_level "$1" && show;;
    fixed)
        mhz="${2:?fixed MHZ}"; read -r rlo rhi < <(range)
        (( mhz >= rlo && mhz <= rhi )) || { echo "gpu-clock: $mhz MHz is outside the driver's range $rlo-$rhi" >&2; exit 2; }
        save && w $D/power_dpm_force_performance_level manual && w $D/pp_od_clk_voltage "s 0 $mhz" && w $D/pp_od_clk_voltage "s 1 $mhz" && w $D/pp_od_clk_voltage c && show;;
    *) echo "usage: gpu-clock.sh show|save|auto|high|fixed MHZ|restore" >&2; exit 2;;
esac
