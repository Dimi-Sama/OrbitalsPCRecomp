@echo off
setlocal
rem SwitchRecomp: downloads what's missing into this folder, with internet and nothing else to do (no admin rights,
rem nothing gets installed on the system): Python (to recompile games) and GCC (makes recompiled games faster).
rem SwitchRecomp opens it by itself when Python is missing.
title SwitchRecomp - Install
cd /d "%~dp0" || exit /b 1
echo SwitchRecomp: installing what is missing (into this folder, nothing goes on the system)
echo.
set "PY=python\python.exe"
if exist "%PY%" goto havepy
echo Python 3.14 (about 16 MB, once)
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "tools\bootstrap-python.ps1"
if errorlevel 1 goto python_failed
if not exist "%PY%" goto python_failed
echo   done
echo.
:havepy
"%PY%" -u -I "tool\get_deps.py"
if errorlevel 1 goto compiler_failed
if /I "%~1"=="--no-pause" exit /b 0
echo.
echo This window closes by itself in 15 seconds.
timeout /t 15 >nul
exit /b 0
:python_failed
echo Python setup failed. The specific cause is shown above.
goto finish_error
:compiler_failed
echo Compiler setup failed. See the details above and retry.
:finish_error
echo.
if /I "%~1"=="--no-pause" exit /b 1
pause
exit /b 1
