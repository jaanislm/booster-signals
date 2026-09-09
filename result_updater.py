from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Dict, Optional, List

import requests
from dotenv import load_dotenv

from database import supabase


# =========================================================
# BOOSTER RESULT UPDATER V1.1
# =========================================================

UPDATER_VERSION = "1.1.0"

load_dotenv()

TZ = ZoneInfo("America/Sao_Paulo")

API_KEY = os.getenv("TWELVE_DATA_API_KEY")

if not API_KEY:
    raise RuntimeError(
        "TWELVE_DATA_API_KEY não encontrada."
    )

TWELVE_DATA_URL = (
    "https://api.twelvedata.com/time_series"
)

# Twelve Data Basic
SAFE_REQUESTS_PER_MINUTE = 7

# O REST pode demorar para disponibilizar candle fechado.
# Vamos esperar pelo menos 2 minutos após a expiração.
RESULT_DELAY_SECONDS = 120

REQUEST_TIMEOUT = 30

# Controle local
request_timestamps: List[float] = []


# =========================================================
# DATETIME
# =========================================================

def parse_datetime(value: str) -> datetime:

    dt = datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)

    return dt.astimezone(TZ)


# =========================================================
# RATE LIMIT LOCAL
# =========================================================

def wait_for_local_quota():

    global request_timestamps

    now = time.time()

    # Mantém apenas chamadas feitas nos últimos 60s
    request_timestamps = [
        timestamp
        for timestamp in request_timestamps
        if now - timestamp < 60
    ]

    if (
        len(request_timestamps)
        < SAFE_REQUESTS_PER_MINUTE
    ):
        return

    oldest = min(request_timestamps)

    wait_seconds = (
        61 - (now - oldest)
    )

    if wait_seconds > 0:

        print(
            f"⏳ Quota local: aguardando "
            f"{wait_seconds:.0f}s..."
        )

        time.sleep(wait_seconds)

    now = time.time()

    request_timestamps = [
        timestamp
        for timestamp in request_timestamps
        if now - timestamp < 60
    ]


def register_request():

    request_timestamps.append(
        time.time()
    )


# =========================================================
# TWELVE DATA REQUEST
# =========================================================

def twelve_data_request(
    params: Dict[str, Any],
    retry_429: bool = True,
) -> Dict[str, Any]:

    wait_for_local_quota()

    response = requests.get(
        TWELVE_DATA_URL,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )

    register_request()

    # -----------------------------------------------------
    # Headers de quota
    # -----------------------------------------------------

    credits_used = response.headers.get(
        "api-credits-used"
    )

    credits_left = response.headers.get(
        "api-credits-left"
    )

    if (
        credits_used is not None
        or credits_left is not None
    ):
        print(
            "   API credits"
            f" | usados: {credits_used}"
            f" | restantes: {credits_left}"
        )

    # -----------------------------------------------------
    # 429
    # -----------------------------------------------------

    if response.status_code == 429:

        if retry_429:

            print(
                "⏳ Limite da Twelve Data atingido. "
                "Aguardando reset..."
            )

            time.sleep(61)

            return twelve_data_request(
                params,
                retry_429=False,
            )

        raise RuntimeError(
            "Limite da Twelve Data continua "
            "indisponível após o reset."
        )

    # -----------------------------------------------------
    # Outros HTTP errors
    #
    # Não usamos raise_for_status() para evitar
    # imprimir URL contendo a API KEY.
    # -----------------------------------------------------

    if not response.ok:

        raise RuntimeError(
            "Erro HTTP da Twelve Data: "
            f"{response.status_code}"
        )

    try:

        payload = response.json()

    except ValueError:

        raise RuntimeError(
            "Resposta inválida da Twelve Data."
        )

    if payload.get("status") == "error":

        raise RuntimeError(
            payload.get(
                "message",
                "Erro retornado pela Twelve Data.",
            )
        )

    return payload


# =========================================================
# EXPIRY PRICE
# =========================================================

def get_expiry_price(
    symbol: str,
    expiry_time: datetime,
) -> Optional[float]:

    """
    Para uma expiração às 15:10:

    buscamos o candle 1M iniciado às 15:09.

    O CLOSE desse candle representa o preço
    imediatamente anterior à virada para 15:10.
    """

    target_minute = (
        expiry_time
        - timedelta(minutes=1)
    ).replace(
        second=0,
        microsecond=0,
    )

    start_date = (
        target_minute
        - timedelta(minutes=2)
    )

    end_date = (
        target_minute
        + timedelta(minutes=2)
    )

    params = {
        "symbol": symbol,
        "interval": "1min",

        "start_date":
            start_date.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),

        "end_date":
            end_date.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),

        "timezone":
            "America/Sao_Paulo",

        "apikey":
            API_KEY,

        "format":
            "JSON",
    }

    payload = twelve_data_request(
        params
    )

    values = payload.get(
        "values",
        []
    )

    if not values:
        return None

    # =====================================================
    # IMPORTANTE:
    # Não pegamos simplesmente "o mais próximo".
    #
    # Queremos especificamente o candle correspondente
    # ao minuto da expiração.
    # =====================================================

    for candle in values:

        raw_datetime = candle.get(
            "datetime"
        )

        if not raw_datetime:
            continue

        candle_dt = datetime.fromisoformat(
            raw_datetime
        )

        if candle_dt.tzinfo is None:
            candle_dt = candle_dt.replace(
                tzinfo=TZ
            )

        candle_dt = candle_dt.astimezone(
            TZ
        ).replace(
            second=0,
            microsecond=0,
        )

        if candle_dt == target_minute:

            try:

                return float(
                    candle["close"]
                )

            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                return None

    return None


# =========================================================
# RESULT
# =========================================================

def calculate_result(
    direction: str,
    entry_price: float,
    exit_price: float,
) -> str:

    direction = (
        direction
        .strip()
        .upper()
    )

    if direction == "BUY":

        if exit_price > entry_price:
            return "WIN"

        if exit_price < entry_price:
            return "LOSS"

        return "DRAW"

    if direction == "SELL":

        if exit_price < entry_price:
            return "WIN"

        if exit_price > entry_price:
            return "LOSS"

        return "DRAW"

    raise ValueError(
        f"Direção inválida: {direction}"
    )


# =========================================================
# PENDING SIGNALS
# =========================================================

def get_pending_signals():

    # Só processa sinais cuja expiração aconteceu
    # há pelo menos RESULT_DELAY_SECONDS.

    cutoff = (
        datetime.now(TZ)
        - timedelta(
            seconds=RESULT_DELAY_SECONDS
        )
    )

    response = (
        supabase
        .table("signals")
        .select(
            "id,"
            "symbol,"
            "direction,"
            "entry_time,"
            "expiry_time,"
            "entry_price,"
            "result,"
            "is_mock"
        )
        .is_(
            "result",
            "null",
        )
        .eq(
            "is_mock",
            False,
        )
        .lte(
            "expiry_time",
            cutoff.isoformat(),
        )
        .order(
            "expiry_time"
        )
        .limit(20)
        .execute()
    )

    return response.data or []


# =========================================================
# UPDATE SUPABASE
# =========================================================

def update_signal_result(
    signal_id: int,
    result: str,
    exit_price: float,
):

    response = (
        supabase
        .table("signals")
        .update({
            "result": result,
            "exit_price": exit_price,
        })
        .eq(
            "id",
            signal_id,
        )
        .is_(
            "result",
            "null",
        )
        .execute()
    )

    return response.data


# =========================================================
# PROCESS SIGNAL
# =========================================================

def process_signal(
    signal: Dict[str, Any],
) -> Dict[str, Any]:

    signal_id = signal["id"]
    symbol = signal["symbol"]

    direction = (
        signal["direction"]
        .strip()
        .upper()
    )

    entry_price = signal.get(
        "entry_price"
    )

    if entry_price is None:

        return {
            "id": signal_id,
            "symbol": symbol,
            "status": "SKIPPED",
            "reason":
                "entry_price ausente",
        }

    entry_price = float(
        entry_price
    )

    expiry_time = parse_datetime(
        signal["expiry_time"]
    )

    print("")
    print(
        f"🔎 #{signal_id} "
        f"{symbol} {direction}"
    )

    exit_price = get_expiry_price(
        symbol,
        expiry_time,
    )

    if exit_price is None:

        return {
            "id": signal_id,
            "symbol": symbol,
            "status": "PENDING",
            "reason":
                "candle exato da expiração "
                "ainda indisponível",
        }

    result = calculate_result(
        direction,
        entry_price,
        exit_price,
    )

    updated = update_signal_result(
        signal_id,
        result,
        exit_price,
    )

    if not updated:

        return {
            "id": signal_id,
            "symbol": symbol,
            "status": "SKIPPED",
            "reason":
                "sinal já atualizado "
                "por outro processo",
        }

    return {
        "id": signal_id,
        "symbol": symbol,
        "direction": direction,

        "entry_price":
            entry_price,

        "exit_price":
            exit_price,

        "result":
            result,

        "status":
            "UPDATED",
    }


# =========================================================
# RUN
# =========================================================

def update_pending_results():

    signals = get_pending_signals()

    print("")
    print("=" * 60)
    print(
        f"BOOSTER RESULT UPDATER V{UPDATER_VERSION}"
    )
    print("=" * 60)

    if not signals:

        print(
            "Nenhum sinal vencido pendente."
        )

        return []

    print(
        f"Sinais pendentes encontrados: "
        f"{len(signals)}"
    )

    results = []

    for signal in signals:

        try:

            result = process_signal(
                signal
            )

            results.append(
                result
            )

            status = result.get(
                "status"
            )

            if status == "UPDATED":

                emoji = (
                    "✅"
                    if result["result"] == "WIN"
                    else
                    "❌"
                    if result["result"] == "LOSS"
                    else
                    "➖"
                )

                print(
                    f"{emoji} "
                    f"{result['symbol']} "
                    f"{result['direction']}"
                )

                print(
                    f"   Entrada: "
                    f"{result['entry_price']}"
                )

                print(
                    f"   Saída:   "
                    f"{result['exit_price']}"
                )

                print(
                    f"   Resultado: "
                    f"{result['result']}"
                )

            else:

                print(
                    f"⚠️ {result}"
                )

        except Exception as exc:

            # Não imprime URL/request.
            # Assim não vazamos a API key.

            error = {
                "id":
                    signal.get("id"),

                "symbol":
                    signal.get("symbol"),

                "status":
                    "ERROR",

                "error":
                    str(exc),
            }

            results.append(
                error
            )

            print(
                f"❌ {error}"
            )

    # =====================================================
    # RESUMO
    # =====================================================

    updated_results = [
        result
        for result in results
        if result.get("status")
        == "UPDATED"
    ]

    wins = sum(
        result.get("result") == "WIN"
        for result in updated_results
    )

    losses = sum(
        result.get("result") == "LOSS"
        for result in updated_results
    )

    draws = sum(
        result.get("result") == "DRAW"
        for result in updated_results
    )

    pending = sum(
        result.get("status") == "PENDING"
        for result in results
    )

    errors = sum(
        result.get("status") == "ERROR"
        for result in results
    )

    print("")
    print("=" * 60)
    print("RESUMO")
    print("=" * 60)

    print(
        f"Atualizados: {len(updated_results)}"
    )

    print(
        f"WIN: {wins}"
    )

    print(
        f"LOSS: {losses}"
    )

    print(
        f"DRAW: {draws}"
    )

    print(
        f"PENDING: {pending}"
    )

    print(
        f"ERROR: {errors}"
    )

    return results


if __name__ == "__main__":

    update_pending_results()