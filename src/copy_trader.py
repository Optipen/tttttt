#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Système de copy-trading fictif pour Solana wallets."""

import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ------------------ Configuration ------------------

COPY_TRADER_DB = Path("copy_trader.db")
INITIAL_BALANCE = 10.0  # SOL initial pour simulation
SLIPPAGE_PCT = 0.5  # 0.5% slippage simulé
FEE_PCT = 0.1  # 0.1% fee par transaction

# ------------------ Structures de données ------------------


@dataclass
class Position:
    """Position ouverte fictive."""

    id: int
    wallet: str
    alert_timestamp: float
    alert_profit: float  # Profit détecté dans l'alerte
    alert_signature: str
    entry_price_sol: float  # Prix d'entrée simulé (1 SOL = 1 token par défaut)
    entry_amount_sol: float  # Montant investi en SOL
    entry_fee: float
    status: str  # "open" | "closed" | "stopped"
    exit_timestamp: Optional[float] = None
    exit_price_sol: Optional[float] = None
    exit_amount_sol: Optional[float] = None
    exit_fee: Optional[float] = None
    exit_signature: Optional[str] = None
    pnl_sol: Optional[float] = None
    pnl_pct: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------ Base de données ------------------


def init_copy_trader_db() -> None:
    """Initialise la base de données SQLite pour copy-trading."""
    conn = sqlite3.connect(COPY_TRADER_DB)
    cursor = conn.cursor()

    # Table des positions
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet TEXT NOT NULL,
            alert_timestamp REAL NOT NULL,
            alert_profit REAL NOT NULL,
            alert_signature TEXT NOT NULL,
            entry_price_sol REAL NOT NULL,
            entry_amount_sol REAL NOT NULL,
            entry_fee REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            exit_timestamp REAL,
            exit_price_sol REAL,
            exit_amount_sol REAL,
            exit_fee REAL,
            exit_signature TEXT,
            pnl_sol REAL,
            pnl_pct REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    # Table du solde
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS balance (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            total_sol REAL NOT NULL DEFAULT 10.0,
            locked_sol REAL NOT NULL DEFAULT 0.0,
            available_sol REAL NOT NULL DEFAULT 10.0,
            total_pnl_sol REAL NOT NULL DEFAULT 0.0,
            total_trades INTEGER NOT NULL DEFAULT 0,
            winning_trades INTEGER NOT NULL DEFAULT 0,
            losing_trades INTEGER NOT NULL DEFAULT 0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    # Initialise le solde si vide
    cursor.execute("SELECT COUNT(*) FROM balance")
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            """
            INSERT INTO balance (id, total_sol, locked_sol, available_sol, total_pnl_sol, total_trades, winning_trades, losing_trades)
            VALUES (1, ?, ?, ?, 0.0, 0, 0, 0)
        """,
            (INITIAL_BALANCE, 0.0, INITIAL_BALANCE),
        )

    conn.commit()
    conn.close()


def get_balance() -> Dict[str, float]:
    """Récupère le solde actuel."""
    conn = sqlite3.connect(COPY_TRADER_DB)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT total_sol, locked_sol, available_sol, total_pnl_sol, total_trades, winning_trades, losing_trades FROM balance WHERE id = 1"
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return {
            "total_sol": INITIAL_BALANCE,
            "locked_sol": 0.0,
            "available_sol": INITIAL_BALANCE,
            "total_pnl_sol": 0.0,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
        }

    return {
        "total_sol": row[0],
        "locked_sol": row[1],
        "available_sol": row[2],
        "total_pnl_sol": row[3],
        "total_trades": row[4],
        "winning_trades": row[5],
        "losing_trades": row[6],
    }


def update_balance(
    locked_sol: float, available_sol: float, pnl_delta: float = 0.0, is_win: Optional[bool] = None
) -> None:
    """Met à jour le solde."""
    conn = sqlite3.connect(COPY_TRADER_DB)
    cursor = conn.cursor()

    # Récupère le solde actuel
    cursor.execute(
        "SELECT total_sol, total_pnl_sol, total_trades, winning_trades, losing_trades FROM balance WHERE id = 1"
    )
    row = cursor.fetchone()

    if not row:
        total_sol = INITIAL_BALANCE
        total_pnl = 0.0
        total_trades = 0
        winning_trades = 0
        losing_trades = 0
    else:
        total_sol = row[0]
        total_pnl = row[1]
        total_trades = row[2]
        winning_trades = row[3]
        losing_trades = row[4]

    # Met à jour
    total_sol += pnl_delta
    total_pnl += pnl_delta

    if is_win is not None:
        total_trades += 1
        if is_win:
            winning_trades += 1
        else:
            losing_trades += 1

    cursor.execute(
        """
        UPDATE balance
        SET total_sol = ?, locked_sol = ?, available_sol = ?, total_pnl_sol = ?,
            total_trades = ?, winning_trades = ?, losing_trades = ?, last_updated = CURRENT_TIMESTAMP
        WHERE id = 1
    """,
        (
            total_sol,
            locked_sol,
            available_sol,
            total_pnl,
            total_trades,
            winning_trades,
            losing_trades,
        ),
    )

    conn.commit()
    conn.close()


# ------------------ Gestion des positions ------------------


def open_position(
    wallet: str,
    alert_profit: float,
    alert_signature: str,
    entry_price_sol: float = 1.0,
    position_size_pct: float = 10.0,
) -> Optional[int]:
    """
    Ouvre une position fictive lors d'une alerte.

    Args:
        wallet: Adresse du wallet surveillé
        alert_profit: Profit détecté dans l'alerte (SOL)
        alert_signature: Signature de la transaction d'alerte
        entry_price_sol: Prix d'entrée simulé (par défaut 1.0 pour simplicité)
        position_size_pct: % du solde disponible à investir (défaut 10%)

    Returns:
        ID de la position ouverte, ou None si pas assez de solde
    """
    balance = get_balance()
    available = balance["available_sol"]

    if available < 0.1:  # Minimum 0.1 SOL
        print(f"[COPY] Solde insuffisant: {available:.2f} SOL disponible")
        return None

    # Calcule le montant à investir
    position_size = available * (position_size_pct / 100.0)
    position_size = min(position_size, available * 0.5)  # Max 50% du solde
    position_size = max(position_size, 0.1)  # Min 0.1 SOL

    # Applique slippage et fee
    slippage = position_size * (SLIPPAGE_PCT / 100.0)
    entry_fee = position_size * (FEE_PCT / 100.0)
    actual_entry = position_size - slippage - entry_fee

    if actual_entry < 0.01:
        print(f"[COPY] Position trop petite apres fees: {actual_entry:.4f} SOL")
        return None

    # Crée la position
    conn = sqlite3.connect(COPY_TRADER_DB)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO positions (
            wallet, alert_timestamp, alert_profit, alert_signature,
            entry_price_sol, entry_amount_sol, entry_fee, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'open')
    """,
        (
            wallet,
            time.time(),
            alert_profit,
            alert_signature,
            entry_price_sol,
            actual_entry,
            entry_fee,
        ),
    )

    position_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # Met à jour le solde
    locked = balance["locked_sol"] + position_size
    available_new = balance["available_sol"] - position_size
    update_balance(locked, available_new)

    print(
        f"[COPY] Position ouverte #{position_id} | Wallet {wallet[:8]}... | {actual_entry:.4f} SOL @ {entry_price_sol:.4f} | Alert: +{alert_profit:.2f} SOL"
    )

    return position_id


def close_position(
    position_id: int, exit_price_sol: float, exit_signature: str, exit_reason: str = "wallet_sold"
) -> Optional[float]:
    """
    Ferme une position fictive.

    Args:
        position_id: ID de la position
        exit_price_sol: Prix de sortie simulé
        exit_signature: Signature de la transaction de sortie
        exit_reason: Raison de la fermeture

    Returns:
        PnL en SOL, ou None si position non trouvée
    """
    conn = sqlite3.connect(COPY_TRADER_DB)
    cursor = conn.cursor()

    # Récupère la position
    cursor.execute(
        """
        SELECT entry_amount_sol, entry_price_sol, entry_fee, wallet, locked_sol
        FROM positions
        WHERE id = ? AND status = 'open'
    """,
        (position_id,),
    )

    row = cursor.fetchone()
    if not row:
        conn.close()
        return None

    entry_amount, entry_price, entry_fee, wallet, locked = row

    # Calcule le montant de sortie
    # Simule: on vend au même prix ratio que l'achat
    # Si le wallet a fait +X% de profit, on simule +X% aussi
    exit_amount = entry_amount * (exit_price_sol / entry_price)
    exit_fee = exit_amount * (FEE_PCT / 100.0)
    actual_exit = exit_amount - exit_fee

    # Calcule PnL
    pnl_sol = actual_exit - entry_amount
    pnl_pct = (pnl_sol / entry_amount) * 100.0 if entry_amount > 0 else 0.0

    # Met à jour la position
    cursor.execute(
        """
        UPDATE positions
        SET status = ?, exit_timestamp = ?, exit_price_sol = ?, exit_amount_sol = ?,
            exit_fee = ?, exit_signature = ?, pnl_sol = ?, pnl_pct = ?
        WHERE id = ?
    """,
        (
            exit_reason,
            time.time(),
            exit_price_sol,
            actual_exit,
            exit_fee,
            exit_signature,
            pnl_sol,
            pnl_pct,
        ),
    )

    conn.commit()
    conn.close()

    # Met à jour le solde
    balance = get_balance()
    locked_new = balance["locked_sol"] - entry_amount
    available_new = balance["available_sol"] + actual_exit
    is_win = pnl_sol > 0
    update_balance(locked_new, available_new, pnl_delta=pnl_sol, is_win=is_win)

    print(
        f"[COPY] Position fermee #{position_id} | Wallet {wallet[:8]}... | PnL: {pnl_sol:+.4f} SOL ({pnl_pct:+.2f}%) | {exit_reason}"
    )

    return pnl_sol


def get_open_positions(wallet: Optional[str] = None) -> List[Dict]:
    """Récupère les positions ouvertes."""
    conn = sqlite3.connect(COPY_TRADER_DB)
    cursor = conn.cursor()

    if wallet:
        cursor.execute(
            """
            SELECT * FROM positions WHERE status = 'open' AND wallet = ?
            ORDER BY alert_timestamp DESC
        """,
            (wallet,),
        )
    else:
        cursor.execute(
            """
            SELECT * FROM positions WHERE status = 'open'
            ORDER BY alert_timestamp DESC
        """
        )

    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    conn.close()

    return [dict(zip(columns, row, strict=False)) for row in rows]


def check_wallet_sold(
    wallet: str, new_transactions: List[dict], rpc_manager
) -> List[Tuple[int, str]]:
    """
    Vérifie si un wallet a vendu (détecte une transaction de profit négatif).

    Args:
        wallet: Adresse du wallet
        new_transactions: Nouvelles transactions détectées
        rpc_manager: Manager RPC pour récupérer les détails

    Returns:
        Liste de (position_id, exit_signature) pour les positions à fermer
    """
    # TODO: Implémenter la détection de vente
    # Pour l'instant, on simule en fermant après un certain temps ou si profit négatif détecté
    return []


# ------------------ Interface avec wallet_monitor ------------------


def on_alert(
    wallet: str, alert_profit: float, alert_signature: str, dex: str = "", signal_type: str = ""
) -> Optional[int]:
    """
    Appelé quand une alerte est générée.
    Ouvre automatiquement une position fictive.

    Args:
        wallet: Adresse du wallet
        alert_profit: Profit détecté (SOL)
        alert_signature: Signature de la transaction
        dex: DEX utilisé
        signal_type: Type de signal

    Returns:
        ID de la position ouverte, ou None
    """
    # Taille de position basée sur la confiance du profit
    if alert_profit >= 5.0:
        position_size_pct = 20.0  # 20% pour gros profits
    elif alert_profit >= 2.0:
        position_size_pct = 15.0  # 15% pour profits moyens
    else:
        position_size_pct = 10.0  # 10% pour petits profits

    # Prix d'entrée simulé (simplifié: 1 SOL = 1 token)
    entry_price = 1.0

    return open_position(wallet, alert_profit, alert_signature, entry_price, position_size_pct)


def get_portfolio_summary() -> Dict:
    """Récupère un résumé du portefeuille fictif."""
    balance = get_balance()
    open_positions = get_open_positions()

    # Calcule PnL des positions ouvertes (non réalisé)
    unrealized_pnl = 0.0
    for pos in open_positions:
        # Simule le PnL non réalisé (simplifié)
        pos["entry_amount_sol"]
        # Pour l'instant, on considère que le PnL non réalisé est 0
        unrealized_pnl += 0.0

    return {
        "balance": balance,
        "open_positions_count": len(open_positions),
        "open_positions": open_positions[:10],  # Limite à 10
        "unrealized_pnl_sol": unrealized_pnl,
        "total_value_sol": balance["total_sol"] + unrealized_pnl,
        "win_rate": (balance["winning_trades"] / balance["total_trades"] * 100.0)
        if balance["total_trades"] > 0
        else 0.0,
    }


# ------------------ Initialisation ------------------


def init_copy_trader() -> None:
    """Initialise le système de copy-trading."""
    # [DAAS] WARNING: Copy-trader est désactivé par défaut en mode DaaS
    # Ne pas utiliser en production sans validation manuelle
    import os

    if os.getenv("COPY_TRADER_ENABLED", "").lower() not in ("1", "true", "yes", "on"):
        print("[COPY] ⚠️  WARNING: Copy-trader désactivé par défaut en mode DaaS")
        print("[COPY] ⚠️  Pour activer, définir COPY_TRADER_ENABLED=true explicitement")
        print("[COPY] ⚠️  Mode données uniquement - aucune exécution réelle")
        return

    init_copy_trader_db()
    balance = get_balance()
    print("[COPY] ⚠️  WARNING: Copy-trader activé | Mode simulation uniquement")
    print(
        f"[COPY] Copy-trader initialise | Solde initial: {balance['total_sol']:.2f} SOL | Disponible: {balance['available_sol']:.2f} SOL"
    )
