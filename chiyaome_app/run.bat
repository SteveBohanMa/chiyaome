@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ====== Chiyaome run ======
echo.
set "PY="
py -3.12 -c "import sys" >nul 2>nul && set "PY=py -3.12"
if not defined PY py -3.11 -c "import sys" >nul 2>nul && set "PY=py -3.11"
if not defined PY py -3.10 -c "import sys" >nul 2>nul && set "PY=py -3.10"
if not defined PY py -3.13 -c "import sys" >nul 2>nul && set "PY=py -3.13"
if not defined PY where py >nul 2>nul && set "PY=py"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo [ERROR] No Python found. Install Python 3.12 from https://www.python.org/downloads/
  echo During setup, TICK "Add Python to PATH".
  goto end
)
echo Using: %PY%
%PY% -c "import sys;print('Python', sys.version)"
echo.
echo Installing dependencies (first run only)...
%PY% -m pip install -r requirements.txt
echo Ensuring GUI deps (correct names)...
%PY% -m pip install proxy_tools bottle pythonnet pywin32
echo.
echo Verifying GUI library...
%PY% -c "import webview"
if errorlevel 1 (
  echo webview import failed - trying a clean reinstall...
  %PY% -m pip install --force-reinstall --no-cache-dir pywebview proxy_tools bottle pythonnet pywin32
  %PY% -c "import webview"
  if errorlevel 1 (
    echo [ERROR] webview still cannot import. Please screenshot this and send to me.
    goto end
  )
)
echo   GUI OK. Starting app...
%PY% app.py
if errorlevel 1 (
  echo.
  echo [ERROR] App error. Copy the text above and send it to me.
)
:end
echo.
pause
