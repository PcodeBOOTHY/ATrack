@echo off
rem Academic Weapon launcher for Windows. Double-click this file to run the app.
rem First run: installs Python if needed, sets everything up, asks for your API key.
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Academic Weapon

echo.
echo  ==== Academic Weapon ====
echo.

rem ---- 1. Find Python (the "py" launcher first; plain "python" may be the Store shortcut)
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY python --version >nul 2>nul && set "PY=python"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
if defined PY goto have_python

echo Python isn't installed. Installing it now - this takes a minute or two...
where winget >nul 2>nul
if errorlevel 1 goto no_winget
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
  set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
  goto have_python
)
py -3 --version >nul 2>nul && set "PY=py -3"
if defined PY goto have_python
echo.
echo Python was installed, but Windows needs a fresh start to find it.
echo Close this window and double-click start.bat again.
goto fail

:no_winget
echo.
echo Couldn't install Python automatically.
echo Install it from https://www.python.org/downloads/ - tick "Add python.exe to PATH" -
echo then double-click start.bat again.
start "" https://www.python.org/downloads/
goto fail

:have_python
%PY% --version

rem ---- 2. Private environment for the app's packages (once)
if exist ".venv\Scripts\python.exe" goto have_venv
echo Setting up the app (first run only)...
%PY% -m venv .venv
if errorlevel 1 (
  echo Could not create the environment.
  goto fail
)
:have_venv

rem ---- 3. Install or update packages when requirements.txt changes
fc /b requirements.txt ".venv\requirements.installed" >nul 2>nul
if not errorlevel 1 goto have_packages
echo Installing packages - the first time takes a few minutes...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
  echo.
  echo Package install failed. Check your internet connection and try again.
  goto fail
)
copy /y requirements.txt ".venv\requirements.installed" >nul
:have_packages

rem ---- 4. Settings file with your Anthropic API key (once, or if it still has the placeholder)
if not exist ".env" goto ask_key
findstr /c:"your-key-here" .env >nul 2>nul
if errorlevel 1 goto have_env
:ask_key
echo.
echo The app uses Claude to read syllabi. Get an API key at https://console.anthropic.com
set "AKEY="
set /p "AKEY=Paste your Anthropic API key (sk-ant-...), or press Enter to skip for now: "
> .env echo ANTHROPIC_API_KEY=!AKEY!
>> .env echo ANTHROPIC_MODEL=claude-sonnet-5-5
echo Saved. You can change it later in the .env file.
:have_env

rem ---- 5. Run. The browser opens by itself; closing this window stops the app.
echo.
echo Starting... your browser will open at http://localhost:8501
echo Keep this window open while you use the app. Close it to stop.
echo.
start "" /b cmd /c "ping -n 8 127.0.0.1 >nul & start "" http://localhost:8501"
".venv\Scripts\python.exe" -m streamlit run app.py --server.headless true --browser.gatherUsageStats false
if errorlevel 1 goto fail
goto end

:fail
echo.
pause
exit /b 1

:end
endlocal
