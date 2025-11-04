# Guide de vérification du projet

## Vérification rapide (script automatique)

```powershell
.\scripts\check_all.ps1
```

Ce script vérifie :
- ✅ Lint (ruff)
- ✅ Format (black)
- ✅ Imports (isort)
- ✅ Types (mypy)
- ✅ Tests (pytest avec coverage)

## Correction automatique

```powershell
.\scripts\fix_all.ps1
```

Ce script corrige automatiquement :
- ✅ Format (black)
- ✅ Imports (isort)
- ✅ Lint (ruff - auto-fix)

## Vérification manuelle

### 1. Lint
```powershell
ruff check src/ tests/
```

### 2. Format
```powershell
# Vérifier
black --check src/ tests/

# Corriger
black src/ tests/
```

### 3. Imports
```powershell
# Vérifier
isort --check-only src/ tests/

# Corriger
isort src/ tests/
```

### 4. Types
```powershell
mypy src/ --ignore-missing-imports
```

### 5. Tests
```powershell
# Tous les tests
pytest tests/ -v

# Avec coverage
pytest --cov=src --cov-report=html
```

## Installation des dépendances

```powershell
pip install -r requirements.txt
```

## Commandes utiles

### Vérifier les imports Python
```powershell
python -c "import src.wallet_monitor; print('OK')"
```

### Vérifier la configuration
```powershell
python -c "from src.config import CONFIG; print(CONFIG)"
```

### Lancer le service (dry-run)
```powershell
python -m src.wallet_monitor
```

