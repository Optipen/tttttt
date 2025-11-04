# Script de correction automatique des problemes detectes
# Corrige automatiquement : lint, format, imports

Write-Host "=== Correction automatique du projet ===" -ForegroundColor Cyan
Write-Host ""

$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 1. Ruff auto-fix
Write-Host "[1/3] Correction automatique avec ruff..." -ForegroundColor Yellow
python -m ruff check --fix --unsafe-fixes src/ tests/
if ($LASTEXITCODE -eq 0) {
    Write-Host "  [OK] Ruff auto-fix termine" -ForegroundColor Green
} else {
    Write-Host "  [!] Certaines erreurs ne peuvent pas etre corrigees automatiquement" -ForegroundColor Yellow
}

# 2. Black format
Write-Host ""
Write-Host "[2/3] Formatage avec black..." -ForegroundColor Yellow
python -m black src/ tests/
if ($LASTEXITCODE -eq 0) {
    Write-Host "  [OK] Formatage termine" -ForegroundColor Green
} else {
    Write-Host "  [X] Erreur lors du formatage" -ForegroundColor Red
}

# 3. Isort imports
Write-Host ""
Write-Host "[3/3] Tri des imports avec isort..." -ForegroundColor Yellow
python -m isort src/ tests/
if ($LASTEXITCODE -eq 0) {
    Write-Host "  [OK] Tri des imports termine" -ForegroundColor Green
} else {
    Write-Host "  [X] Erreur lors du tri des imports" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== Termine ===" -ForegroundColor Cyan
Write-Host "Note: Les erreurs de type (mypy) et les tests doivent etre corriges manuellement" -ForegroundColor Yellow

