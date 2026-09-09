from __future__ import annotations

import os
import sys
import asyncio
import threading
import json
from datetime import datetime
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


# =========================================================
# BOOSTER QUOTEX FEED V1.1
# Cache local + atualização incremental
# =========================================================

load_dotenv()

TZ = ZoneInfo("America/Sao_Paulo")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

QUOTEX_LIB_DIR = os.path.join(
    BASE_DIR,
    "quotex-historical-data",
)

CACHE_DIR = os.path.join(
    BASE_DIR,
    "quotex_cache",
)

os.makedirs(CACHE_DIR, exist_ok=True)

if QUOTEX_LIB_DIR not in sys.path:
    sys.path.insert(0, QUOTEX_LIB_DIR)

from pyquotex.stable_api import Quotex


EMAIL = os.getenv("QUOTEX_EMAIL", "")
PASSWORD = os.getenv("QUOTEX_PASSWORD", "")

if not EMAIL or not PASSWORD:
    raise RuntimeError(
        "QUOTEX_EMAIL / QUOTEX_PASSWORD não encontrados no .env"
    )


# Uma conexão por vez.
_quotex_lock = threading.Lock()


# =========================================================
# HELPERS
# =========================================================

def _timestamp_to_datetime(timestamp: int) -> str:
    return datetime.fromtimestamp(
        timestamp,
        TZ,
    ).isoformat()


def _normalize_symbol(symbol: str) -> str:
    return (
        symbol
        .replace("/", "")
        .replace(" ", "")
    )


def _cache_path(symbol: str) -> str:
    safe_symbol = (
        symbol
        .replace("/", "")
        .replace(" ", "")
    )

    return os.path.join(
        CACHE_DIR,
        f"{safe_symbol}_M1.json",
    )


def _load_cache(symbol: str) -> List[Dict[str, Any]]:
    path = _cache_path(symbol)

    if not os.path.exists(path):
        return []

    try:
        with open(
            path,
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        if isinstance(data, list):
            return data

    except Exception:
        pass

    return []


def _save_cache(
    symbol: str,
    candles: List[Dict[str, Any]],
) -> None:

    path = _cache_path(symbol)

    # Mantemos no máximo 3500 M1.
    candles = candles[-3500:]

    with open(
        path,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            candles,
            file,
            ensure_ascii=False,
        )


def _normalize_candles(
    raw_candles,
) -> List[Dict[str, Any]]:

    result = []

    for candle in raw_candles or []:

        timestamp = candle.get("time")

        open_price = candle.get("open")
        high_price = candle.get("high")
        low_price = candle.get("low")
        close_price = candle.get("close")

        if timestamp is None:
            continue

        if None in (
            open_price,
            high_price,
            low_price,
            close_price,
        ):
            continue

        result.append({
            "datetime": _timestamp_to_datetime(
                int(timestamp)
            ),
            "open": float(open_price),
            "high": float(high_price),
            "low": float(low_price),
            "close": float(close_price),
        })

    return result


def _merge_candles(
    old: List[Dict[str, Any]],
    new: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:

    unique = {}

    for candle in old:
        unique[candle["datetime"]] = candle

    for candle in new:
        unique[candle["datetime"]] = candle

    return sorted(
        unique.values(),
        key=lambda item: item["datetime"],
    )


# =========================================================
# QUOTEX
# =========================================================

async def _fetch_async(
    symbol: str,
) -> List[Dict[str, Any]]:

    cached = _load_cache(symbol)

    client = Quotex(
        email=EMAIL,
        password=PASSWORD,
        lang="en",
    )

    client.debug_ws_enable = False

    try:

        connected, message = await asyncio.wait_for(
            client.connect(),
            timeout=20,
        )

        if not connected:
            raise RuntimeError(
                f"{symbol}: Quotex não conectou: {message}"
            )

        quotex_symbol = _normalize_symbol(symbol)

        asset_name, asset_data = (
            await asyncio.wait_for(
                client.get_available_asset(
                    quotex_symbol,
                    force_open=True,
                ),
                timeout=15,
            )
        )

        if not asset_name:
            raise RuntimeError(
                f"{symbol}: ativo não encontrado."
            )

        period = 60

        # ============================================
        # PRIMEIRA CARGA
        # ============================================

        if len(cached) < 2400:

            print(
                f"[QUOTEX] {symbol}: "
                f"cache inicial ainda não existe."
            )

            # Fazemos a carga histórica somente
            # quando realmente necessária.
            duration_seconds = 60 * 60 * 42

            raw = await asyncio.wait_for(
                client.get_candles_deep(
                    asset_name,
                    duration_seconds,
                    period,
                ),
                timeout=90,
            )

        # ============================================
        # ATUALIZAÇÃO
        # ============================================

        else:

            print(
                f"[QUOTEX] {symbol}: "
                f"cache {len(cached)} candles. "
                f"Atualizando..."
            )

            # Apenas uma pequena janela recente.
            duration_seconds = 60 * 30

            raw = await asyncio.wait_for(
                client.get_candles_deep(
                    asset_name,
                    duration_seconds,
                    period,
                ),
                timeout=30,
            )

        new_candles = _normalize_candles(raw)

        merged = _merge_candles(
            cached,
            new_candles,
        )

        if not merged:
            raise RuntimeError(
                f"{symbol}: nenhum candle recebido."
            )

        _save_cache(
            symbol,
            merged,
        )

        print(
            f"[QUOTEX] {symbol}: "
            f"{len(merged)} candles disponíveis."
        )

        return merged

    finally:

        try:
            await client.close()
        except Exception:
            pass


# =========================================================
# INTERFACE PARA scanner.py
# =========================================================

def fetch_1m_quotex(
    symbol: str,
    candle_count: int = 2500,
) -> List[Dict[str, Any]]:

    with _quotex_lock:

        candles = asyncio.run(
            _fetch_async(symbol)
        )

        return candles[-candle_count:]