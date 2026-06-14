@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ====== Chiyaome build (v3.2) ======
echo.
echo Cleaning old build cache (build/ dist/ *.spec) ...
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
del /q *.spec 2>nul
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
echo Installing dependencies (first run is slow, please wait)...
%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt pyinstaller
%PY% -m pip install proxy_tools bottle pythonnet pywin32 pystray Pillow rapidfuzz requests
if errorlevel 1 (
  echo.
  echo [ERROR] Dependency install failed.
  echo If it says: No matching distribution found for onnxruntime
  echo  -^> your Python is too NEW. Install Python 3.12 from python.org and run again.
  goto end
)
echo.
echo NOTE: Shipping a prebuilt drugs.db (4-table v3.2 schema).
echo To (re)build it: run fetch_openfda_full.py to get drugs_en.db, then:  %PY% build_drugs_db_v32.py --en drugs_en.db --compress
set "DBDATA="
if exist drugs.db (
  set "DBDATA=--add-data drugs.db;."
  echo Found drugs.db - it will be bundled.
) else (
  echo [WARN] drugs.db NOT found in this folder.
  echo        Building WITHOUT the drug library; box recognition will not work.
  echo        To fix: copy your drugs.db into this folder and run build.bat again.
)
echo.
echo Building exe (this can take a few minutes)...
%PY% -m PyInstaller --noconfirm --onefile --windowed --name MedicationReminder --icon chiyaome.ico --add-data "web;web" --add-data "alarm.wav;." --add-data "ocr_parse.py;." --add-data "chiyaome.ico;." %DBDATA% --collect-all rapidocr_onnxruntime --collect-all onnxruntime --collect-all pyttsx3 --collect-all webview --collect-all pythonnet --collect-all clr_loader --collect-all proxy_tools --collect-all bottle --collect-all pystray --collect-all PIL --hidden-import pyttsx3.drivers.sapi5 --hidden-import comtypes --hidden-import clr --hidden-import pystray._win32 --hidden-import rapidfuzz --hidden-import drugdb --hidden-import ocr_parse app.py
if errorlevel 1 (
  echo [ERROR] Build failed. Copy the error text above and send it to me.
  goto end
)
echo.
echo ====== DONE ======
echo Output: dist\MedicationReminder.exe
echo (~150-200MB is normal: offline OCR models bundled.)
echo.
:end
echo.
pause
