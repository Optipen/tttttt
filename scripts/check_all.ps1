# Script de verification complete du projet
# Verifie : lint, format, types, tests

$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "=== Verification complete du projet ===" -ForegroundColor Cyan
Write-Host ""

$errors = 0

# 1. Verifier les dependances
Write-Host "[1/6] Verification des dependances..." -ForegroundColor Yellow
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "  [X] Python n'est pas installe ou pas dans PATH" -ForegroundColor Red
    $errors++
    exit 1
}

Write-Host "  [OK] Python trouve" -ForegroundColor Green

# 2. Lint avec ruff
Write-Host ""
Write-Host "[2/6] Lint avec ruff..." -ForegroundColor Yellow
pip install ruff mypy black isort pytest pytest-cov pytest-asyncio --quiet 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [!] Impossible d'installer les outils de verification" -ForegroundColor Yellow
}

python -m ruff check src/ tests/
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [X] Erreurs de lint detectees" -ForegroundColor Red
    $errors++
} else {
    Write-Host "  [OK] Lint OK" -ForegroundColor Green
}

# 3. Format avec black
Write-Host ""
Write-Host "[3/6] Verification du format avec black..." -ForegroundColor Yellow
python -m black --check src/ tests/
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [X] Problemes de format detectes (executez: python -m black src/ tests/)" -ForegroundColor Red
    $errors++
} else {
    Write-Host "  [OK] Format OK" -ForegroundColor Green
}

# 4. Verification des imports avec isort
Write-Host ""
Write-Host "[4/6] Verification des imports avec isort..." -ForegroundColor Yellow
python -m isort --check-only src/ tests/
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [X] Problemes d'ordre d'imports detectes (executez: python -m isort src/ tests/)" -ForegroundColor Red
    $errors++
} else {
    Write-Host "  [OK] Imports OK" -ForegroundColor Green
}

# 5. Type checking avec mypy
Write-Host ""
Write-Host "[5/6] Type checking avec mypy..." -ForegroundColor Yellow
python -m mypy src/ --ignore-missing-imports
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [X] Erreurs de type detectees" -ForegroundColor Red
    $errors++
} else {
    Write-Host "  [OK] Types OK" -ForegroundColor Green
}

# 6. Tests
Write-Host ""
Write-Host "[6/6] Execution des tests..." -ForegroundColor Yellow
python -m pytest tests/ -v --cov=src --cov-report=term-missing
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [X] Tests echoues" -ForegroundColor Red
    $errors++
} else {
    Write-Host "  [OK] Tous les tests passent" -ForegroundColor Green
}

# Resume
Write-Host ""
Write-Host "=== Resume ===" -ForegroundColor Cyan
if ($errors -eq 0) {
    Write-Host "[OK] Tous les checks sont OK ! Le projet est pret." -ForegroundColor Green
    exit 0
} else {
    Write-Host "[X] $errors probleme(s) detecte(s)" -ForegroundColor Red
    exit 1
}

