#!/usr/bin/env bash
# deck-queue.sh FILE: runs the deck-run.sh command lines of FILE one after the other, after any Orbitals already running ends.
# Start it detached from the SSH session: systemd-run --user --unit=orbitals-queue --collect bash tools/deck-queue.sh tools/queue.txt
# A line "quota=N% <deck-run arguments>" runs that run in a scope limited to N % CPU (cgroup cpu.max, no root).
# Progress in /tmp/deck-queue.log; "queue done" at the end.
here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$here/.." || exit 1
log=/tmp/deck-queue.log; : > "$log"
while pgrep -x Orbitals >/dev/null; do sleep 10; done
while IFS= read -r line; do
  [[ -z "$line" || "$line" == \#* ]] && continue
  quota=""; if [[ "$line" == quota=* ]]; then quota="${line%% *}"; quota="${quota#quota=}"; line="${line#* }"; fi
  echo "$(date +%T) start ${quota:+quota $quota }$line" >> "$log"
  if [[ -n "$quota" ]]; then eval "systemd-run --user --scope -q -p CPUQuota=$quota bash tools/deck-run.sh $line" >> "$log" 2>&1
  else eval "bash tools/deck-run.sh $line" >> "$log" 2>&1; fi
done < "$1"
echo "$(date +%T) queue done" >> "$log"
