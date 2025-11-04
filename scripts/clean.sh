#!/usr/bin/env bash
set -euo pipefail

find . -type d -name "__pycache__" -prune -exec rm -rf {} +
rm -rf .pytest_cache htmlcov logs tmp cache
find . -type f \( -name "*.db" -o -name "*.log" \) -delete

echo "🧹 Nettoyage terminé."

