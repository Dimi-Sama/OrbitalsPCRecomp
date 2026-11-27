@echo off
setlocal
cd /d "%~dp0"
echo.
echo Orbitals - Diagnostic Issue 11
echo A - Traduction synchrone
echo B - Traduction asynchrone
echo C - Traduction asynchrone et attente ciblee
echo Q - Quitter
echo.
set "ORBITALS_TEST_MODE="
choice /C ABCQ /N /M "Choisis A, B, C ou Q "
if errorlevel 4 exit /b 0
if errorlevel 3 set "ORBITALS_TEST_MODE=C"
if not defined ORBITALS_TEST_MODE if errorlevel 2 set "ORBITALS_TEST_MODE=B"
if not defined ORBITALS_TEST_MODE set "ORBITALS_TEST_MODE=A"
call "%~dp0Orbitals-Launcher.bat" --issue11-test %ORBITALS_TEST_MODE%
exit /b %errorlevel%
