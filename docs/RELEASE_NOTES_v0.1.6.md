# Liftoff — Orbitals PC Recomp v0.1.6

Liftoff is an unofficial native PC port of Orbitals for Windows and Linux, including Steam Deck. It is built on SwitchRecomp by MZ Labs. You compile the game on your own PC from your own copy.

## Updating

Upgrading from v0.1.5 requires one recompilation. Open the new kit, select your existing installation in **Game Files** if prompted,
and choose **Check installed code**. Liftoff keeps your saves, profiles and shader cache. If you already compiled the game with a
0.1.6 candidate, Liftoff can reuse that module when its build fingerprint matches. It can reuse compatible compiler objects during
a rebuild and restore the previous runtime and module after a successful update. [Update guide](../launcher/README.md#updating-an-installation)

## Launcher and installation

- **Liftoff.** The refreshed launcher supports controller navigation, high-DPI displays, settings that save automatically and
  cancellation for supported tasks. Add Liftoff to Steam from the **Tools** page. [Launcher guide](../launcher/README.md)
- **NUP installation.** Liftoff and RecompLauncher Easy Setup extract the base game's ExeFS and RomFS from NUP v1 archives with
  bundled updates or DLC. Setup also accepts a folder containing `exefs/` and `romfs/`. Quiver can launch the game after setup in Liftoff.
  [External launcher setup](../launcher/README.md#external-launchers)
- **Moved and portable installations.** Liftoff reconnects missing extracted-game folders and can keep a compatible module in place.
  Create `portable.txt` beside the launcher to keep its data in `portable-data/`.
  [Portable setup](../launcher/README.md#start)
- **Windows setup and launch.** The Python bootstrap verifies the download and extracts the ZIP with .NET, including on PCs with GNU
  tar first on `PATH`. Build-tool downloads with pinned checksums can retry with Windows curl if Python rejects the TLS certificate.
  The runtime can open long RomFS paths in the session folders used by RecompLauncher and Quiver.
  [Issue #1](https://github.com/Dimi-Sama/OrbitalsPCRecomp/issues/1)

## Graphics and controls

- **TV output.** Choose an aspect ratio in **Settings → Graphics → Display**. TV mode offers 1080p by default, up to 2160p at 16:9,
  experimental 2560×1080 and 3440×1440 at 21:9, and experimental 3840×1080 and 5120×1440 at 32:9. Some menus and videos retain their
  original framing. Internal 3D resolution has its own setting. [Graphics settings](../GRAPHICS_SETTINGS.md) ·
  [Issue #8](https://github.com/Dimi-Sama/OrbitalsPCRecomp/issues/8)
- **Controls.** Xbox and PlayStation layouts supply matching prompts. Bottom-button accept requires the generated configuration layer
  to load from directory-backed RomFS. Nintendo controls are the default. Windows supports opt-in motion aiming with a compatible
  SDL3 controller. [Gyro guide](gyro.md) · [Button layouts](BUTTON_LAYOUT.md)
- **RDNA1 loading and rendering.** RADV NAVI10 and NAVI14 request 32-lane subgroups for fragment shaders and the three particle-sort
  compute passes. xTuniKx validated the fix on an RX 5700 XT in two short sessions, with GPU write-back comparison on and off.
  Both sessions ran without a device loss or rendering breaks, and the cinematic skip button displayed correctly.
  [Issue #7](https://github.com/Dimi-Sama/OrbitalsPCRecomp/issues/7)
- **NVIDIA rendering.** Two shader workarounds address flashes in the opening scenes and broken outlines on the ship hull. The
  graphics shader precision change also applies to vertex and fragment shaders on AMD. [Issue #2](https://github.com/Dimi-Sama/OrbitalsPCRecomp/issues/2)
- **Vulkan write-backs and diagnostics.** Dispatch write-backs reserve memory before submission and keep comparison snapshots alive
  until completion. Device-local snapshots are optional. **Settings → General → Diagnostics → GPU write-back comparison** switches
  between GPU and CPU comparison on the next launch. Logs include the driver, subgroup settings and original device-loss error. The
  runtime enables targeted buffer robustness on RADV GFX10. The Windows diagnostic runner also compares replay and fence-wait modes.
  [Write-back details](vulkan-writeback.md) · [Replay comparison](../TEST-ISSUE11.md)

## Known issues

- The startup logos can still show the wrong colours. [Issue #4](https://github.com/Dimi-Sama/OrbitalsPCRecomp/issues/4)
- A preview tester reported remaining rendering glitches on RTX 4080. The shader precision change for the RX 9070 XT contours and
  missing prompts still needs confirmation on the reported setup. [RTX 4080 report](https://github.com/Dimi-Sama/OrbitalsPCRecomp/issues/2#issuecomment-7211432335) ·
  [Issue #15](https://github.com/Dimi-Sama/OrbitalsPCRecomp/issues/15)
- Higher TV resolutions can be costly on Steam Deck. Both 32:9 resolutions were checked on Windows.

## Credits

- **Vinicius Stanula (`ViniciusStanula`)** contributed the launcher refresh, controller navigation, high-DPI support and settings improvements.
  [PR #3](https://github.com/Dimi-Sama/OrbitalsPCRecomp/pull/3)
- **Leonardo Zerpa (`leonardozerpa2497`)** contributed the TV resolution hook and launcher setting that underpin native ultrawide, the
  gyro implementation, Vulkan write-back lifetime fixes and device-local snapshots, and the controller layout and menu button support.
  [PR #5](https://github.com/Dimi-Sama/OrbitalsPCRecomp/pull/5) · [PR #6](https://github.com/Dimi-Sama/OrbitalsPCRecomp/pull/6) ·
  [PR #12](https://github.com/Dimi-Sama/OrbitalsPCRecomp/pull/12) · [PR #16](https://github.com/Dimi-Sama/OrbitalsPCRecomp/pull/16) ·
  [PR #17](https://github.com/Dimi-Sama/OrbitalsPCRecomp/pull/17)
- **Xarishark** contributed the RecompLauncher setup and play integration. [PR #10](https://github.com/Dimi-Sama/OrbitalsPCRecomp/pull/10)
- **KingsmanZer0** diagnosed the NVIDIA cockpit flashes and hull outlines, shared the shader patch and tested it on RTX 4090. The shader
  precision work for AMD builds on that patch. KingsmanZer0 also reported the startup logo colours. **`youdeend3`** reported the ship
  rendering glitches, **`rodrigeoBR`** confirmed the original patch on RTX 4060, and **`gabriel26101995-art`** reported the remaining glitch on RTX 4080.
  **`slimx`** pointed to **`pete842`**'s shared-memory work in Lichii.
  [Patch and diagnosis](https://github.com/Dimi-Sama/OrbitalsPCRecomp/issues/2#issuecomment-7183991749) ·
  [RTX 4060 confirmation](https://github.com/Dimi-Sama/OrbitalsPCRecomp/issues/2#issuecomment-7213530322) · [Lichii PR #2082](https://github.com/zortos293/Lichii/pull/2082) ·
  [Issue #4](https://github.com/Dimi-Sama/OrbitalsPCRecomp/issues/4)
- **`justifun`** reported the Python setup failure. **`asdad3mgg-boop`** requested ultrawide and explained how recurring rebuilds made
  updates impractical. **Trasterin** reported the broken links after moving an installation and proposed portable data.
  [Issue #1](https://github.com/Dimi-Sama/OrbitalsPCRecomp/issues/1) · [Update feedback](https://github.com/Dimi-Sama/OrbitalsPCRecomp/issues/8#issuecomment-7210859167) ·
  [Issue #13](https://github.com/Dimi-Sama/OrbitalsPCRecomp/issues/13) · [Issue #14](https://github.com/Dimi-Sama/OrbitalsPCRecomp/issues/14)
- **`lustrousdragon`** offered to test 32:9 at 5120×1440 and suggested 3840×1080 as a lower-resolution option.
  [Issue #8 · Testing offer](https://github.com/Dimi-Sama/OrbitalsPCRecomp/issues/8#issuecomment-7214740602) ·
  [Issue #8 · 3840×1080 suggestion](https://github.com/Dimi-Sama/OrbitalsPCRecomp/issues/8#issuecomment-7215991143)
- **`xTuniKx`** tested every RDNA1 build and validated the fix on an RX 5700 XT. They shared the crash and validation logs.
  **Grazorus** provided diagnostics for the low-frame-rate report, and **`mayacaalahussle-cmd`** reported the RX 9070 XT contours and missing prompts.
  [Issue #7](https://github.com/Dimi-Sama/OrbitalsPCRecomp/issues/7) · [Issue #11](https://github.com/Dimi-Sama/OrbitalsPCRecomp/issues/11) ·
  [Issue #15](https://github.com/Dimi-Sama/OrbitalsPCRecomp/issues/15)
