# Script pour pousser le projet vers GitHub
# Usage: .\scripts\push_to_github.ps1 <github-url>
# Exemple: .\scripts\push_to_github.ps1 https://github.com/username/repo.git

param(
    [Parameter(Mandatory=$true)]
    [string]$GitHubUrl
)

$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "=== Push vers GitHub ===" -ForegroundColor Cyan
Write-Host ""

# Verifier que Git est initialise
if (-not (Test-Path ".git")) {
    Write-Host "[X] Le depot Git n'est pas initialise" -ForegroundColor Red
    Write-Host "Executez d'abord: git init" -ForegroundColor Yellow
    exit 1
}

# Verifier l'URL GitHub
if ($GitHubUrl -notmatch "^https://github\.com/|^git@github\.com:") {
    Write-Host "[!] L'URL GitHub semble invalide: $GitHubUrl" -ForegroundColor Yellow
    Write-Host "Format attendu: https://github.com/username/repo.git" -ForegroundColor Yellow
    $confirm = Read-Host "Continuer quand meme? (o/n)"
    if ($confirm -ne "o") {
        exit 1
    }
}

# Ajouter le remote (ou le remplacer s'il existe)
Write-Host "[1/3] Configuration du remote GitHub..." -ForegroundColor Yellow
$remoteExists = git remote get-url origin 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "  Remote 'origin' existe deja: $remoteExists" -ForegroundColor Yellow
    $replace = Read-Host "  Remplacer par $GitHubUrl ? (o/n)"
    if ($replace -eq "o") {
        git remote set-url origin $GitHubUrl
        Write-Host "  [OK] Remote mis a jour" -ForegroundColor Green
    } else {
        Write-Host "  Remote non modifie" -ForegroundColor Yellow
    }
} else {
    git remote add origin $GitHubUrl
    Write-Host "  [OK] Remote ajoute" -ForegroundColor Green
}

# Verifier qu'il y a des commits
Write-Host ""
Write-Host "[2/3] Verification des commits..." -ForegroundColor Yellow
$commitCount = (git rev-list --count HEAD 2>$null)
if ($LASTEXITCODE -ne 0 -or $commitCount -eq 0) {
    Write-Host "  [X] Aucun commit trouve" -ForegroundColor Red
    Write-Host "  Executez d'abord: git add . && git commit -m 'Initial commit'" -ForegroundColor Yellow
    exit 1
}
Write-Host "  [OK] $commitCount commit(s) trouve(s)" -ForegroundColor Green

# Push vers GitHub
Write-Host ""
Write-Host "[3/3] Push vers GitHub..." -ForegroundColor Yellow
Write-Host "  URL: $GitHubUrl" -ForegroundColor Gray
Write-Host "  Branche: main" -ForegroundColor Gray

# Essayer de pousser vers main
git push -u origin main 2>&1 | Tee-Object -Variable pushOutput

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "[OK] Push reussi vers GitHub!" -ForegroundColor Green
} else {
    # Si main n'existe pas, essayer master
    Write-Host ""
    Write-Host "  Tentative avec la branche 'master'..." -ForegroundColor Yellow
    git push -u origin master 2>&1 | Tee-Object -Variable pushOutput
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "[OK] Push reussi vers GitHub!" -ForegroundColor Green
    } else {
        Write-Host ""
        Write-Host "[X] Echec du push" -ForegroundColor Red
        Write-Host ""
        Write-Host "Sortie:" -ForegroundColor Yellow
        Write-Host $pushOutput
        Write-Host ""
        Write-Host "Solutions possibles:" -ForegroundColor Yellow
        Write-Host "  1. Verifiez que le depot GitHub existe" -ForegroundColor Gray
        Write-Host "  2. Verifiez vos credentials Git/GitHub" -ForegroundColor Gray
        Write-Host "  3. Creer le depot sur GitHub d'abord: https://github.com/new" -ForegroundColor Gray
        Write-Host "  4. Utiliser un token d'acces: git remote set-url origin https://<token>@github.com/user/repo.git" -ForegroundColor Gray
        exit 1
    }
}

Write-Host ""
Write-Host "=== Termine ===" -ForegroundColor Cyan

