# Launcher controls and output resolution

The upstream Tk launcher keeps its existing colors, surfaces, three-column fields,
header and tabs. Controls and Graphics scroll vertically when their rows exceed the
window. This is a desktop UI (minimum 880×650), not a phone layout. Do not import the
night branch's typography, navigation, assets or page redesign.

Controls were adapted from `night/launcher-layout-selection` (`18ebfae`). Nintendo
and gyro Off remain the defaults, including profiles created before these settings.
Xbox/PlayStation select both glyph layout and western bottom-button accept/back;
Nintendo clears both overrides, including a retired independent accept checkbox.

**Companion runtimes required:** the layout selectors require the separate button
layout runtime change. Gyro requires the gyro runtime (PR #12), SDL and a controller
with motion sensors. This launcher commit does not implement either runtime feature
or upgrade an installed runtime. Its Controls page states these dependencies.
Calibration is consumed after a successful process start with gyro enabled; keep the
controller still. A failed process start leaves the request pending.

Settings belong to each save profile. A launch writes an isolated session INI,
replaces only owned keys, preserves unknown settings, and leaves the installation's
INI untouched. Settings are locked during a game or background operation.
