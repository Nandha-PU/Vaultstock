@echo off
set VAULTSTOCK_DEMO_MODE=1
set VAULTSTOCK_RELOAD=1

if exist "C:\Users\Nandha\AppData\Local\Programs\Python\Python313\python.exe" (
    "C:\Users\Nandha\AppData\Local\Programs\Python\Python313\python.exe" "%~dp0run_dev.py"
) else (
    py -3 "%~dp0run_dev.py" 2>nul || python "%~dp0run_dev.py"
)
