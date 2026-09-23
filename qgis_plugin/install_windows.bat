@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_windows.ps1" -PluginName "muuntaja_qgis"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" echo Asennus epaonnistui. Tarkista ylla oleva virhe.
if /I not "%~1"=="--quiet" pause
exit /b %RESULT%
