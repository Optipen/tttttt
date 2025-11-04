FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install curl pour healthcheck
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# [CLEANUP] : Chemins mis à jour pour la nouvelle structure
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ /app/src/
COPY data/ /app/data/
COPY config/ /app/config/
RUN chown -R root:root /app

RUN useradd -m -d /home/walletbot walletbot
USER walletbot

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8001/healthz || exit 1

# [CLEANUP] : Chemin mis à jour pour la nouvelle structure
CMD ["python", "-m", "src.wallet_monitor"]

