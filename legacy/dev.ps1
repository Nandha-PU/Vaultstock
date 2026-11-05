# VaultStock Dev Launcher for PowerShell
param(
    [string]$PythonExe = ""
)

$env:VAULTSTOCK_DEMO_MODE = "1"
$env:VAULTSTOCK_RELOAD = "1"

if (-not $PythonExe) {
    if (Test-Path "C:\Users\Nandha\AppData\Local\Programs\Python\Python313\python.exe") {
        $PythonExe = "C:\Users\Nandha\AppData\Local\Programs\Python\Python313\python.exe"
    } else {
        $PythonExe = "python"
    }
}

& $PythonExe (Join-Path $PSScriptRoot "run_dev.py")
