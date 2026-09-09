from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from scanner import (
    scan_market,
    register_cooldown,
)
from database import save_signal


# =========================================================
# BOOSTER API V2.1
# =========================================================

API_VERSION = "2.1.0"
ENGINE_VERSION = "1.2.0"

TZ = ZoneInfo("America/Sao_Paulo")

EXPIRY_MINUTES = 10


app = FastAPI(
    title="Booster Signals API",
    version=API_VERSION,
)


# =========================================================
# CORS
# DEV: liberado
# Depois restringimos ao domínio do Lovable.
# =========================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# HELPERS
# =========================================================

def next_full_minute() -> datetime:

    now = datetime.now(TZ)

    return (
        now.replace(
            second=0,
            microsecond=0,
        )
        + timedelta(minutes=1)
    )


def build_db_payload(
    best: Dict[str, Any],
    entry_time: datetime,
    expiry_time: datetime,
) -> Dict[str, Any]:

    """
    IMPORTANTE:
    Só colocamos aqui colunas que já existem
    na tabela public.signals do Supabase.
    """

    return {
        "symbol": best["symbol"],
        "market_type": best.get(
            "market_type",
            "NORMAL",
        ),
        "direction": best["direction"],
        "grade": best["grade"],

        "entry_time":
            entry_time.isoformat(),

        "expiry_time":
            expiry_time.isoformat(),

        "expiry_minutes":
            EXPIRY_MINUTES,

        "entry_price":
            best.get("price"),

        "buy_score":
            best.get("buy_score"),

        "sell_score":
            best.get("sell_score"),

        "edge":
            best.get("edge"),

        "trend_10m":
            best.get("trend_10m"),

        "trend_15m":
            best.get("trend_15m"),

        "trend_30m":
            best.get("trend_30m"),

        "trend_1h":
            best.get("trend_1h"),

        "adx_10m":
            best.get("adx_10m"),

        "adx_15m":
            best.get("adx_15m"),

        "confirmations":
            best.get(
                "confirmations",
                [],
            ),

        "result": None,
        "exit_price": None,

        "engine_version":
            best.get(
                "engine_version",
                ENGINE_VERSION,
            ),

        "is_mock": False,
    }


def build_api_signal(
    best: Dict[str, Any],
    signal_id: Any,
    entry_time: datetime,
    expiry_time: datetime,
) -> Dict[str, Any]:

    return {
        "id": signal_id,

        "symbol":
            best["symbol"],

        "market_type":
            best.get(
                "market_type",
                "NORMAL",
            ),

        "direction":
            best["direction"],

        "grade":
            best["grade"],

        # NÃO é probabilidade.
        "score":
            best.get(
                "ranking_score",
            ),

        "setup_type":
            best.get(
                "setup_type",
            ),

        "entry_time":
            entry_time.isoformat(),

        "expiry_time":
            expiry_time.isoformat(),

        "expiry_minutes":
            EXPIRY_MINUTES,

        "price":
            best.get("price"),

        "entry_price":
            best.get("price"),

        "buy_score":
            best.get("buy_score"),

        "sell_score":
            best.get("sell_score"),

        "edge":
            best.get("edge"),

        "confirmations":
            best.get(
                "confirmations",
                [],
            ),

        "vetoes":
            best.get(
                "vetoes",
                [],
            ),

        "market": {
            "10m":
                best.get(
                    "trend_10m"
                ),

            "15m":
                best.get(
                    "trend_15m"
                ),

            "30m":
                best.get(
                    "trend_30m"
                ),

            "1h":
                best.get(
                    "trend_1h"
                ),
        },

        "market_state": {
            "10m":
                best.get(
                    "market_state_10m"
                ),

            "15m":
                best.get(
                    "market_state_15m"
                ),

            "30m":
                best.get(
                    "market_state_30m"
                ),

            "1h":
                best.get(
                    "market_state_1h"
                ),
        },

        "adx": {
            "10m":
                best.get(
                    "adx_10m"
                ),

            "15m":
                best.get(
                    "adx_15m"
                ),
        },

        "candle": {
            "buy_score":
                best.get(
                    "candle_score_buy"
                ),

            "sell_score":
                best.get(
                    "candle_score_sell"
                ),

            "signals_10m":
                best.get(
                    "candle_signals_10m",
                    [],
                ),

            "signals_15m":
                best.get(
                    "candle_signals_15m",
                    [],
                ),

            "contradiction":
                best.get(
                    "candle_contradiction",
                    False,
                ),

            "contradiction_reason":
                best.get(
                    "candle_contradiction_reason"
                ),
        },

        "risk_status":
            best.get(
                "risk_status",
                "APROVADO",
            ),

        "engine_version":
            best.get(
                "engine_version",
                ENGINE_VERSION,
            ),

        "is_mock": False,

        # O resultado começa pendente.
        "result": None,
        "exit_price": None,
    }


# =========================================================
# ROOT
# =========================================================

@app.get("/")
def root():

    return {
        "app": "Booster Signals",
        "status": "online",
        "api_version": API_VERSION,
        "engine_version": ENGINE_VERSION,
        "timezone":
            "America/Sao_Paulo",
    }


# =========================================================
# HEALTH
# =========================================================

@app.get("/health")
def health():

    return {
        "status": "ok",
        "api_version":
            API_VERSION,

        "engine_version":
            ENGINE_VERSION,

        "timezone":
            "America/Sao_Paulo",
    }


# =========================================================
# SCANNER
#
# Consultar scanner NÃO gera cooldown.
# =========================================================

@app.get("/scanner")
def scanner_endpoint():

    try:

        result = scan_market(
            force_refresh=False
        )

        return {
            "success": True,
            **result,
        }

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


# =========================================================
# GENERATE SIGNAL
# =========================================================

@app.post("/generate-signal")
def generate_signal():

    try:

        market = scan_market(
            force_refresh=False
        )

        best = market.get(
            "best"
        )

        # ---------------------------------------------
        # Nenhuma oportunidade
        # ---------------------------------------------

        if not best:

            return {
                "success": True,
                "signal": False,

                "message":
                    "Nenhuma entrada A/A+ "
                    "disponível agora.",

                "data": None,

                "ranking":
                    market.get(
                        "ranking",
                        [],
                    ),

                "approved":
                    market.get(
                        "approved",
                        [],
                    ),

                "blocked":
                    market.get(
                        "blocked",
                        [],
                    ),
            }

        # ---------------------------------------------
        # Horário
        # ---------------------------------------------

        entry_time = (
            next_full_minute()
        )

        expiry_time = (
            entry_time
            + timedelta(
                minutes=EXPIRY_MINUTES
            )
        )

        # ---------------------------------------------
        # Banco
        # ---------------------------------------------

        db_payload = (
            build_db_payload(
                best,
                entry_time,
                expiry_time,
            )
        )

        saved = save_signal(
            db_payload
        )

        if not saved:
            raise RuntimeError(
                "Supabase não confirmou "
                "o salvamento do sinal."
            )

        saved_row = saved[0]

        signal_id = (
            saved_row.get("id")
        )

        # =============================================
        # COOLDOWN
        #
        # SOMENTE AGORA.
        #
        # O sinal já foi realmente criado e salvo.
        # =============================================

        register_cooldown(
            best["symbol"]
        )

        # ---------------------------------------------
        # Response
        # ---------------------------------------------

        signal_data = (
            build_api_signal(
                best,
                signal_id,
                entry_time,
                expiry_time,
            )
        )

        return {
            "success": True,
            "signal": True,

            "message":
                "Oportunidade encontrada.",

            "data":
                signal_data,

            "ranking":
                market.get(
                    "ranking",
                    [],
                ),

            "approved":
                market.get(
                    "approved",
                    [],
                ),

            "blocked":
                market.get(
                    "blocked",
                    [],
                ),
        }

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )