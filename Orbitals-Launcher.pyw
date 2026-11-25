# Orbitals PC Recomp launcher, for a shortcut or a pin on the Windows taskbar: the launcher package of this folder, from any folder.
import os
import runpy
import sys

here = os.path.dirname(os.path.abspath(__file__))
os.chdir(here)
sys.path.insert(0, here)
runpy.run_module("launcher", run_name="__main__")
