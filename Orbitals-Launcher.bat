@echo off
rem Orbitals PC Recomp launcher (launcher\README.md). It needs Python 3.12+ with Tk, the python.org one: the Python that Install.bat
rem downloads for the recompiler has no Tk. Nothing else is installed here: the launcher's "Install from my files" downloads
rem the build tools into this folder, each checked against its pinned SHA-256.
setlocal
cd /d "%~dp0"
set "PYL="
for %%C in ("py -3.14" "py -3.13" "py -3.12" "python") do (
  if not defined PYL (
    %%~C -c "import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul && set "PYL=%%~C"
  )
)
rem the launcher runs in its own window, without a console (pyw / pythonw); this window closes at once
if not defined PYL goto nopython
set "PYW=pythonw"
if /i "%PYL:~0,3%"=="py " set "PYW=pyw %PYL:~3%"
start "" %PYW% -B -m launcher %*
exit /b 0
:nopython
echo.
echo The launcher needs Python 3.12 or newer with Tk (the python.org installer includes it).
echo.
where winget >nul 2>nul
if errorlevel 1 goto manual
choice /c YN /m "Install Python 3.13 for this user now with winget (from python.org)"
if errorlevel 2 goto manual
winget install -e --id Python.Python.3.13 --scope user --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto manual
echo.
echo Python is installed. Run Orbitals-Launcher.bat again (a new window sees the new Python).
pause
exit /b 0
:manual
echo Install Python 3.12+ from https://www.python.org/downloads/windows/ (keep "tcl/tk and IDLE" checked),
echo then run Orbitals-Launcher.bat again. Without the launcher: see README.md, "Windows - one command".
pause
exit /b 1
