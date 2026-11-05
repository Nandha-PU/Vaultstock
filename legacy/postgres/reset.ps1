# ============================================================================
# VaultStock: reset.ps1
# Automates PostgreSQL database recreation on Windows
# ============================================================================

param(
    [string]$DbName = "vaultstock",
    [string]$DbUser = "postgres",
    [string]$DbHost = "localhost",
    [int]$DbPort = 5432
)

Write-Host ">>> Rebuilding VaultStock database '$DbName' on $DbHost:$DbPort..." -ForegroundColor Cyan

# Terminate connections and recreate database
$dropSql = "DROP DATABASE IF EXISTS $DbName WITH (FORCE); CREATE DATABASE $DbName;"
& psql -h $DbHost -p $DbPort -U $DbUser -c $dropSql

if ($LASTEXITCODE -ne 0) {
    Write-Warning "Failed to drop/recreate database via psql. Ensure PostgreSQL service is running."
}

Write-Host ">>> Applying VaultStock SQL scripts in sequence..." -ForegroundColor Green
$scripts = @("01_schema.sql", "02_triggers.sql", "03_roles.sql", "04_views.sql", "05_seed.sql")

foreach ($s in $scripts) {
    Write-Host "--> Running $s..." -ForegroundColor Yellow
    & psql -h $DbHost -p $DbPort -U $DbUser -d $DbName -f (Join-Path $PSScriptRoot $s)
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Error applying $s. Terminating reset."
        exit $LASTEXITCODE
    }
}

Write-Host ">>> Verification test on cryptographic audit log:" -ForegroundColor Green
& psql -h $DbHost -p $DbPort -U $DbUser -d $DbName -c "SELECT * FROM verify_audit_chain();"

Write-Host ">>> Database reset complete!" -ForegroundColor Cyan
