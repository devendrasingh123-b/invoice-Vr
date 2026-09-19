@echo off
cd /d "%~dp0"
echo Starting Invoice Management...
echo API: http://127.0.0.1:8000/docs
echo App: http://127.0.0.1:5173
echo.
start "Invoice API" cmd /k ".venv\Scripts\uvicorn.exe app.main:app --reload --reload-dir backend --app-dir backend --host 127.0.0.1 --port 8000"
timeout /t 3 /nobreak >nul
start "Invoice UI" cmd /k "cd /d "%~dp0frontend" && npm run dev"
echo Chrome/browser: open http://127.0.0.1:5173
pause
