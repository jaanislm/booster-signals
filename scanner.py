from __future__ import annotations

import os
import time
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

import requests
from dotenv import load_dotenv

from engine import analyze_tf, build_signal
from quotex_feed import fetch_1m_quotex


# =========================================================
# BOOSTER SCANNER V1.3
# 16 pares + controle de quota + cache + correlação
# =========================================================

load_dotenv()

TZ = ZoneInfo("America/Sao_Paulo")

API_KEY = os.getenv("TWELVE_DATA_API_KEY")

if not API_KEY:
    raise RuntimeError("TWELVE_DATA_API_KEY não encontrada.")

TWELVE_DATA_URL = "https://api.twelvedata.com/time_series"

OUTPUTSIZE = 5000
EXPIRY_MINUTES = 10
SCANNER_VERSION = "1.3.0"

# Plano Basic = 8 créditos/min.
# Deixamos o scanner trabalhar em lotes de até 8.
BATCH_SIZE = 8
BATCH_WAIT_SECONDS = 61

CACHE_TTL_SECONDS = 60 * 5

_cache_lock = threading.Lock()

_market_cache = {
    "timestamp": 0.0,
    "data": None,
}


# =========================================================
# ASSETS
# =========================================================

ASSETS = [
    "EUR/USD",
    "GBP/USD",
    "EUR/JPY",
    "EUR/GBP",
    "GBP/JPY",
    "AUD/USD",
    "AUD/JPY",
    "USD/JPY",

    "USD/CAD",
    "USD/CHF",
    "NZD/USD",
    "EUR/AUD",
    "EUR/CAD",
    "EUR/CHF",
    "GBP/AUD",
    "GBP/CAD",
]


# =========================================================
# COOLDOWN
# IMPORTANTE:
# scanner NÃO registra cooldown.
# A API fará isso somente quando entregar um sinal.
# =========================================================

COOLDOWN_SECONDS = 15 * 60

_asset_cooldown: Dict[str, float] = {}


def cooldown_active(symbol: str) -> bool:
    timestamp = _asset_cooldown.get(symbol)

    if timestamp is None:
        return False

    return (time.time() - timestamp) < COOLDOWN_SECONDS


def register_cooldown(symbol: str):
    """
    Chamar somente quando o sinal for realmente entregue.
    Não chamar durante scan_market().
    """
    _asset_cooldown[symbol] = time.time()


def cooldown_remaining(symbol: str) -> int:
    timestamp = _asset_cooldown.get(symbol)

    if timestamp is None:
        return 0

    remaining = COOLDOWN_SECONDS - (time.time() - timestamp)

    return max(0, int(remaining))


# =========================================================
# CORRELATION
# =========================================================

def currency_exposure(
    symbol: str,
    direction: str,
) -> Dict[str, str]:

    base, quote = symbol.split("/")

    if direction == "BUY":
        return {
            base: "LONG",
            quote: "SHORT",
        }

    return {
        base: "SHORT",
        quote: "LONG",
    }


def signals_correlated(
    a: Dict[str, Any],
    b: Dict[str, Any],
) -> bool:

    if not a.get("direction") or not b.get("direction"):
        return False

    exposure_a = currency_exposure(
        a["symbol"],
        a["direction"],
    )

    exposure_b = currency_exposure(
        b["symbol"],
        b["direction"],
    )

    for currency in exposure_a:
        if (
            currency in exposure_b
            and exposure_a[currency] == exposure_b[currency]
        ):
            return True

    return False


# =========================================================
# TWELVE DATA
# =========================================================

def fetch_1m(
    symbol: str,
    max_retries: int = 2,
) -> List[Dict[str, Any]]:

    params = {
        "symbol": symbol,
        "interval": "1min",
        "outputsize": OUTPUTSIZE,
        "apikey": API_KEY,
        "timezone": "America/Sao_Paulo",
        "format": "JSON",
    }

    for attempt in range(max_retries + 1):

        try:
            response = requests.get(
                TWELVE_DATA_URL,
                params=params,
                timeout=30,
            )

            # ---------------------------------------------
            # Rate limit
            # ---------------------------------------------

            if response.status_code == 429:

                if attempt >= max_retries:
                    raise RuntimeError(
                        f"{symbol}: limite da Twelve Data atingido"
                    )

                print(
                    f"[QUOTA] {symbol}: aguardando próximo minuto..."
                )

                time.sleep(61)
                continue

            response.raise_for_status()

            payload = response.json()

            if payload.get("status") == "error":
                raise RuntimeError(
                    f"{symbol}: "
                    f"{payload.get('message', 'erro Twelve Data')}"
                )

            values = payload.get("values")

            if not values:
                raise RuntimeError(
                    f"{symbol}: nenhum candle retornado"
                )

            candles = []

            # Twelve Data retorna mais recente primeiro.
            for item in reversed(values):
                candles.append({
                    "datetime": item["datetime"],
                    "open": float(item["open"]),
                    "high": float(item["high"]),
                    "low": float(item["low"]),
                    "close": float(item["close"]),
                })

            return candles

        except requests.RequestException as exc:

            if attempt >= max_retries:
                raise RuntimeError(
                    f"{symbol}: falha HTTP: {exc}"
                )

            time.sleep(3)

    raise RuntimeError(
        f"{symbol}: não foi possível obter candles"
    )


# =========================================================
# TIME
# =========================================================

def parse_dt(value: str) -> datetime:

    dt = datetime.fromisoformat(value)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)

    return dt.astimezone(TZ)


def floor_time(
    dt: datetime,
    minutes: int,
) -> datetime:

    minute = (dt.minute // minutes) * minutes

    return dt.replace(
        minute=minute,
        second=0,
        microsecond=0,
    )


# =========================================================
# AGGREGATION
# =========================================================

def aggregate(
    candles: List[Dict[str, Any]],
    minutes: int,
) -> List[Dict[str, Any]]:

    buckets: Dict[
        datetime,
        List[Dict[str, Any]]
    ] = {}

    for candle in candles:

        dt = parse_dt(candle["datetime"])
        bucket = floor_time(dt, minutes)

        buckets.setdefault(
            bucket,
            [],
        ).append(candle)

    aggregated = []

    now = datetime.now(TZ)

    for bucket_time in sorted(buckets.keys()):

        group = buckets[bucket_time]

        bucket_end = (
            bucket_time.timestamp()
            + minutes * 60
        )

        # Ignorar candle ainda aberto.
        if now.timestamp() < bucket_end:
            continue

        # Evitar timeframe incompleto.
        if len(group) < minutes:
            continue

        group = sorted(
            group,
            key=lambda x: parse_dt(
                x["datetime"]
            ),
        )

        aggregated.append({
            "datetime": bucket_time.isoformat(),
            "open": group[0]["open"],
            "high": max(
                candle["high"]
                for candle in group
            ),
            "low": min(
                candle["low"]
                for candle in group
            ),
            "close": group[-1]["close"],
        })

    return aggregated


# =========================================================
# RANKING
# =========================================================

def grade_points(grade: str) -> int:

    if grade == "A+":
        return 30

    if grade == "A":
        return 20

    return 0


# =========================================================
# ANALYZE ASSET
# =========================================================

def analyze_asset(
    symbol: str,
) -> Dict[str, Any]:

    candles_1m = fetch_1m_quotex(symbol)

    tf10_candles = aggregate(
        candles_1m,
        10,
    )

    tf15_candles = aggregate(
        candles_1m,
        15,
    )

    tf30_candles = aggregate(
        candles_1m,
        30,
    )

    tf60_candles = aggregate(
        candles_1m,
        60,
    )

    minimum = min(
        len(tf10_candles),
        len(tf15_candles),
        len(tf30_candles),
        len(tf60_candles),
    )

    if minimum < 40:
        raise RuntimeError(
            f"{symbol}: candles agregados insuficientes"
        )

    tf10 = analyze_tf(
        tf10_candles,
        "10M",
    )

    tf15 = analyze_tf(
        tf15_candles,
        "15M",
    )

    tf30 = analyze_tf(
        tf30_candles,
        "30M",
    )

    tf60 = analyze_tf(
        tf60_candles,
        "1H",
    )

    signal = build_signal(
        tf10,
        tf15,
        tf30,
        tf60,
    )

    grade = signal["grade"]
    direction = signal["direction"]

    edge = signal["edge"]

    adx10 = tf10.get(
        "adx",
        0,
    )

    adx15 = tf15.get(
        "adx",
        0,
    )

    candle_buy = signal.get(
        "candle_score_buy",
        0,
    )

    candle_sell = signal.get(
        "candle_score_sell",
        0,
    )

    candle_edge = abs(
        candle_buy - candle_sell
    )

    # -----------------------------------------------------
    # Candle contrário
    # -----------------------------------------------------

    contradiction = False
    contradiction_reason = None
    contradiction_penalty = 0

    if direction == "BUY":

        if candle_sell >= 3:
            contradiction = True
            contradiction_penalty = min(
                candle_sell,
                5,
            )

            contradiction_reason = (
                "pressão vendedora detectada "
                "nos candles"
            )

    elif direction == "SELL":

        if candle_buy >= 3:
            contradiction = True
            contradiction_penalty = min(
                candle_buy,
                5,
            )

            contradiction_reason = (
                "pressão compradora detectada "
                "nos candles"
            )

    ranking_score = (
        grade_points(grade)
        + edge
        + min(adx15, 40) / 4
        + min(adx10, 40) / 8
        + min(candle_edge, 8) / 2
        - contradiction_penalty
    )

    price = candles_1m[-1]["close"]

    return {
        "symbol": symbol,
        "market_type": "NORMAL",

        "direction": direction,
        "grade": grade,

        "expiry_minutes": EXPIRY_MINUTES,

        "buy_score": signal["buy_score"],
        "sell_score": signal["sell_score"],
        "edge": edge,

        "ranking_score": round(
            ranking_score,
            2,
        ),

        "price": price,

        "setup_type": signal.get(
            "setup_type"
        ),

        # ---------------------------------------------
        # Trends
        # ---------------------------------------------

        "trend_10m": tf10.get("trend"),
        "trend_15m": tf15.get("trend"),
        "trend_30m": tf30.get("trend"),
        "trend_1h": tf60.get("trend"),

        # ---------------------------------------------
        # Market states
        # ---------------------------------------------

        "market_state_10m": tf10.get(
            "market_state"
        ),

        "market_state_15m": tf15.get(
            "market_state"
        ),

        "market_state_30m": tf30.get(
            "market_state"
        ),

        "market_state_1h": tf60.get(
            "market_state"
        ),

        # ---------------------------------------------
        # Strength
        # ---------------------------------------------

        "adx_10m": round(
            adx10,
            2,
        ),

        "adx_15m": round(
            adx15,
            2,
        ),

        "plus_di_15m": round(
            tf15.get(
                "plus_di",
                0,
            ),
            2,
        ),

        "minus_di_15m": round(
            tf15.get(
                "minus_di",
                0,
            ),
            2,
        ),

        # ---------------------------------------------
        # Candle Engine
        # ---------------------------------------------

        "candle_score_buy": candle_buy,
        "candle_score_sell": candle_sell,

        "candle_signals_10m": tf10.get(
            "candle_signals",
            [],
        ),

        "candle_signals_15m": tf15.get(
            "candle_signals",
            [],
        ),

        "candle_contradiction": contradiction,

        "candle_contradiction_reason":
            contradiction_reason,

        "candle_contradiction_penalty":
            contradiction_penalty,

        # ---------------------------------------------
        # Signal
        # ---------------------------------------------

        "confirmations": signal.get(
            "confirmations",
            [],
        ),

        "vetoes": signal.get(
            "vetoes",
            [],
        ),

        # Scanner só CONSULTA cooldown.
        "cooldown": cooldown_active(
            symbol
        ),

        "cooldown_remaining":
            cooldown_remaining(symbol),

        "signal_time":
            datetime.now(TZ).isoformat(),

        "engine_version":
            signal.get(
                "engine_version"
            ),

        "scanner_version":
            SCANNER_VERSION,
    }


# =========================================================
# RISK FILTER
# =========================================================

def apply_risk_filters(
    opportunities: List[Dict[str, Any]],
) -> Dict[str, Any]:

    approved = []
    blocked = []

    for original in opportunities:

        candidate = dict(original)

        # ---------------------------------------------
        # Cooldown
        # ---------------------------------------------

        if cooldown_active(
            candidate["symbol"]
        ):

            candidate["risk_status"] = (
                "BLOQUEADO_COOLDOWN"
            )

            candidate["risk_reason"] = (
                "ativo em cooldown"
            )

            blocked.append(candidate)

            continue

        # ---------------------------------------------
        # Candle contradiction
        # ---------------------------------------------

        if (
            candidate.get(
                "candle_contradiction"
            )
            and candidate.get(
                "candle_contradiction_penalty",
                0,
            ) >= 4
        ):

            candidate["risk_status"] = (
                "BLOQUEADO_CANDLE"
            )

            candidate["risk_reason"] = (
                candidate.get(
                    "candle_contradiction_reason"
                )
            )

            blocked.append(candidate)

            continue

        # ---------------------------------------------
        # Correlation
        # ---------------------------------------------

        correlated = None

        for accepted in approved:

            if signals_correlated(
                candidate,
                accepted,
            ):
                correlated = accepted
                break

        if correlated is not None:

            candidate["risk_status"] = (
                "BLOQUEADO_CORRELACAO"
            )

            candidate["risk_reason"] = (
                "exposição correlacionada "
                f"com {correlated['symbol']}"
            )

            blocked.append(candidate)

            continue

        # ---------------------------------------------
        # Approved
        # ---------------------------------------------

        candidate["risk_status"] = (
            "APROVADO"
        )

        candidate["risk_reason"] = None

        approved.append(candidate)

    return {
        "approved": approved,
        "blocked": blocked,
    }


# =========================================================
# PROCESS BATCH
# =========================================================

def process_batch(
    symbols: List[str],
) -> tuple[
    List[Dict[str, Any]],
    List[Dict[str, str]],
]:

    results = []
    errors = []

    # Até 8 chamadas dentro do lote.
    with ThreadPoolExecutor(
        max_workers=min(
            len(symbols),
            BATCH_SIZE,
        )
    ) as executor:

        futures = {
            executor.submit(
                analyze_asset,
                symbol,
            ): symbol
            for symbol in symbols
        }

        for future in as_completed(
            futures
        ):

            symbol = futures[future]

            try:

                result = future.result()

                results.append(
                    result
                )

            except Exception as exc:

                errors.append({
                    "symbol": symbol,

                    # NÃO colocamos URL aqui.
                    # Isso evita vazar API key.
                    "error": str(exc),
                })

    return results, errors


# =========================================================
# SCANNER
# =========================================================

def scan_market(
    force_refresh: bool = False,
) -> Dict[str, Any]:

    now = time.time()

    # -----------------------------------------------------
    # CACHE
    # -----------------------------------------------------

    with _cache_lock:

        cached = _market_cache[
            "data"
        ]

        age = (
            now
            - _market_cache[
                "timestamp"
            ]
        )

        if (
            not force_refresh
            and cached is not None
            and age < CACHE_TTL_SECONDS
        ):

            cached_copy = dict(
                cached
            )

            cached_copy[
                "from_cache"
            ] = True

            cached_copy[
                "cache_age_seconds"
            ] = round(
                age,
                1,
            )

            return cached_copy

    print("")
    print("=" * 60)
    print("BOOSTER SCANNER V1.3")
    print("=" * 60)

    results = []
    errors = []

    batches = [
        ASSETS[i:i + BATCH_SIZE]
        for i in range(
            0,
            len(ASSETS),
            BATCH_SIZE,
        )
    ]

    for index, batch in enumerate(
        batches
    ):

        print("")
        print(
            f"Lote {index + 1}/"
            f"{len(batches)}"
        )

        print(
            "Ativos:",
            ", ".join(batch),
        )

        batch_results, batch_errors = (
            process_batch(batch)
        )

        results.extend(
            batch_results
        )

        errors.extend(
            batch_errors
        )

        # ---------------------------------------------
        # Esperar reset de créditos
        # ---------------------------------------------

        if index < len(batches) - 1:

            print("")
            print(
                "Aguardando reset da quota "
                "da Twelve Data..."
            )

            time.sleep(
                BATCH_WAIT_SECONDS
            )

    # -----------------------------------------------------
    # Ranking
    # -----------------------------------------------------

    ranking = sorted(
        results,
        key=lambda x: x[
            "ranking_score"
        ],
        reverse=True,
    )

    opportunities = [
        item
        for item in ranking
        if (
            item["grade"]
            in ("A", "A+")
            and item["direction"]
            in ("BUY", "SELL")
        )
    ]

    # -----------------------------------------------------
    # Risk manager
    # -----------------------------------------------------

    risk = apply_risk_filters(
        opportunities
    )

    approved = risk[
        "approved"
    ]

    blocked = risk[
        "blocked"
    ]

    best = (
        dict(approved[0])
        if approved
        else None
    )

    if best:

        best["priority"] = (
            "RECOMENDADA"
        )

        # MUITO IMPORTANTE:
        #
        # NÃO registramos cooldown aqui.
        #
        # Apenas consultar o scanner
        # não significa que o usuário
        # recebeu/executou o sinal.

    response = {
        "scanned_at":
            datetime.now(
                TZ
            ).isoformat(),

        "scanner_version":
            SCANNER_VERSION,

        "assets_total":
            len(ASSETS),

        "assets_scanned":
            len(results),

        "assets_failed":
            len(errors),

        "opportunities_total":
            len(opportunities),

        "approved_total":
            len(approved),

        "blocked_total":
            len(blocked),

        "best":
            best,

        "ranking":
            ranking,

        "approved":
            approved,

        "blocked":
            blocked,

        "errors":
            errors,

        "from_cache":
            False,

        "cache_ttl_seconds":
            CACHE_TTL_SECONDS,
    }

    # -----------------------------------------------------
    # SAVE CACHE
    # -----------------------------------------------------

    with _cache_lock:

        _market_cache[
            "timestamp"
        ] = time.time()

        _market_cache[
            "data"
        ] = response

    return response


# =========================================================
# LOCAL TEST
# =========================================================

if __name__ == "__main__":

    import json

    result = scan_market(
        force_refresh=True
    )

    print("")
    print("=" * 60)
    print("RESULTADO")
    print("=" * 60)

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )