# SwitchRecomp - Copyright 2026 MZ Labs

import argparse
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from .core import LauncherError, data_home, instance_lock, setup_logging
from .look import sharp_windows
from .ui import Launcher


def main():
    parser = argparse.ArgumentParser(description="Orbitals Recomp Launcher")
    parser.add_argument("--data-dir", type=Path, default=data_home(), help="local folder of the profiles")
    parser.add_argument("--game-dir", type=Path, help="select an Orbitals installation")
    args = parser.parse_args()
    sharp_windows()
    root = tk.Tk()
    root.withdraw()
    try:
        local = args.data_dir.resolve()
        with instance_lock(local), setup_logging(local):
            Launcher(root, local, args.game_dir)
            root.deiconify()
            root.mainloop()
    except (LauncherError, OSError, ValueError) as error:
        messagebox.showerror("Orbitals Recomp", str(error), parent=root)
        root.destroy()
        return 1
    except Exception as error:   # a bug of the launcher itself: said in a window, not only in a log nobody sees
        import traceback
        log = args.data_dir / "logs"
        messagebox.showerror("Orbitals Recomp",
                             f"The launcher hit an internal error and has to close:\n\n{type(error).__name__}: {error}\n\n"
                             f"Please report it (GitHub issues) with the launcher log from:\n{log}", parent=root)
        traceback.print_exc()
        root.destroy()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
