# SwitchRecomp - Copyright 2026 MZ Labs

import argparse
import sys
from pathlib import Path


def liftoff(argv=None):
    import tkinter as tk
    from tkinter import messagebox

    from . import desktop, fonts
    from .core import LauncherError, data_home, instance_lock, launch_kit, migrate_portable_data, portable_kit, setup_logging
    from .look import sharp_windows
    from .ui import Launcher

    parser = argparse.ArgumentParser(description="Orbitals Recomp Launcher")
    parser.add_argument("--data-dir", type=Path, help="local folder of the profiles")
    parser.add_argument("--game-dir", type=Path, help="select an Orbitals installation")
    parser.add_argument("--portable-kit", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    sharp_windows()
    fonts.load()
    desktop.identity()
    root = tk.Tk(className="OrbitalsPCRecomp")
    root.withdraw()
    local = args.data_dir or data_home()
    try:
        kit = portable_kit() if args.data_dir is None else None
        if args.portable_kit and args.data_dir:
            previous = args.portable_kit.resolve()
            if args.data_dir.resolve() == (previous / "portable-data").resolve() and (previous / "portable.txt").is_file():
                kit = previous
        default = data_home().resolve()
        local = (kit / "portable-data" if kit else local).resolve()
        if kit and local != default and not local.exists() and (default / "launcher.json").is_file():
            if messagebox.askyesno("Portable data",
                                   "Copy existing profiles, saves and shader cache into the portable folder?\n\n"
                                   "This can take a few minutes. The original data stays where it is.\n\n"
                                   "Choose No to start with a new portable profile.", parent=root):
                migrate_portable_data(default, local, kit)
        with instance_lock(local), setup_logging(local):
            app = Launcher(root, local, args.game_dir, kit=kit)
            root.deiconify()
            root.mainloop()
        if getattr(app, "next_kit", None):
            launch_kit(*app.next_kit)
    except (LauncherError, OSError, ValueError) as error:
        messagebox.showerror("Orbitals Recomp", str(error), parent=root)
        root.destroy()
        return 1
    except Exception as error:   # a bug of the launcher itself: said in a window, not only in a log nobody sees
        import traceback
        log = local / "logs"
        messagebox.showerror("Orbitals Recomp",
                             f"The launcher hit an internal error and has to close:\n\n{type(error).__name__}: {error}\n\n"
                             f"Please report it (GitHub issues) with the launcher log from:\n{log}", parent=root)
        traceback.print_exc()
        root.destroy()
        return 1
    return 0


def main():
    if sys.argv[1:2] == ["--issue11-test"]:
        from .issue11_preview import main as issue11_preview

        return issue11_preview(sys.argv[2:])
    if sys.argv[1:2] in (["--prepare"], ["--play"]):
        from .recomplauncher import main as managed

        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        return managed(sys.argv[1:], open_liftoff=liftoff)
    return liftoff()


if __name__ == "__main__":
    raise SystemExit(main())
