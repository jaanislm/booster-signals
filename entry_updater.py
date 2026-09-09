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
# BOOSTER ENTRY UPDATER V1.0
# =========================================================

UPDATER_VERSION = "1.0.0"

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

REQUEST_TIMEOUT = 30

# Margem para o candle aparecer no REST
ENTRY_DELAY_SECONDS = 90

# Mantemos abaixo do limite de 8/min.
SAFE_REQUESTS_PER_MINUTE = 7

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
# RATE LIMIT
# =========================================================

def wait_for_local_quota():

    global request_timestamps

    now = time.time()

    request_timestamps = [
        ts
        for ts in request_timestamps
        if now - ts < 60
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
            f"⏳ Quota local: "
            f"aguardando {wait_seconds:.0f}s..."
        )

        time.sleep(wait_seconds)

    now = time.time()

    request_timestamps = [
        ts
        for ts in request_timestamps
        if now - ts < 60
    ]


def register_request():

    request_timestamps.append(
        time.time()
    )


# =========================================================
# TWELVE DATA
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

    credits_used = response.headers.get(
        "api-credits-used"
    )

    credits_left = response.headers.get(
        "api-credits-left"
    )

    print(
        f"   API credits | usados: "
        f"{credits_used} | restantes: "
        f"{credits_left}"
    )

    if response.status_code == 429:

        if retry_429:

            print(
                "⏳ Limite atingido. "
                "Aguardando reset..."
            )

            time.sleep(61)

            return twelve_data_request(
                params,
                retry_429=False,
            )

        raise RuntimeError(
            "Limite da Twelve Data "
            "continua indisponível."
        )

    if not response.ok:

        raise RuntimeError(
            "Erro HTTP Twelve Data: "
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
                "Erro da Twelve Data.",
            )
        )

    return payload


# =========================================================
# PREÇO REAL DE ENTRADA
# =========================================================

def get_entry_price(
    symbol: str,
    entry_time: datetime,
) -> Optional[float]:

    """
    Se o Booster informou entrada às 21:15:00,
    buscamos especificamente o candle 1M iniciado
    às 21:15.

    O OPEN desse candle será usado como preço
    de referência da entrada.
    """

    target_minute = entry_time.replace(
        second=0,
        microsecond=0,
    )

    start_date = (
        target_minute
        - timedelta(minutes=1)
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

        candle_dt = (
            candle_dt
            .astimezone(TZ)
            .replace(
                second=0,
                microsecond=0,
            )
        )

        if candle_dt == target_minute:

            try:

                return float(
                    candle["open"]
                )

            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                return None

    return None


# =========================================================
# BUSCAR SINAIS QUE PRECISAM DE CORREÇÃO
# =========================================================

def get_signals_to_update():

    """
    IMPORTANTE:

    Não vamos alterar sinais antigos que já possuem
    resultado WIN/LOSS.

    Esta versão trabalha apenas com sinais ainda
    PENDENTES, evitando reescrever nosso histórico
    anterior.
    """

    cutoff = (
        datetime.now(TZ)
        - timedelta(
            seconds=ENTRY_DELAY_SECONDS
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
            "entry_time",
            cutoff.isoformat(),
        )
        .order(
            "entry_time"
        )
        .limit(20)
        .execute()
    )

    return response.data or []


# =========================================================
# ATUALIZAR SUPABASE
# =========================================================

def update_entry_price(
    signal_id: int,
    entry_price: float,
):

    response = (
        supabase
        .table("signals")
        .update({
            "entry_price": entry_price,
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
# PROCESSAR SINAL
# =========================================================

def process_signal(
    signal: Dict[str, Any],
) -> Dict[str, Any]:

    signal_id = signal["id"]
    symbol = signal["symbol"]

    old_price = signal.get(
        "entry_price"
    )

    entry_time = parse_datetime(
        signal["entry_time"]
    )

    print("")
    print(
        f"🔎 #{signal_id} "
        f"{symbol}"
    )

    print(
        f"   Entrada programada: "
        f"{entry_time.isoformat()}"
    )

    print(
        f"   Preço do scanner: "
        f"{old_price}"
    )

    real_price = get_entry_price(
        symbol,
        entry_time,
    )

    if real_price is None:

        return {
            "id": signal_id,
            "symbol": symbol,
            "status": "PENDING",
            "reason":
                "candle exato da entrada "
                "ainda indisponível",
        }

    updated = update_entry_price(
        signal_id,
        real_price,
    )

    if not updated:

        return {
            "id": signal_id,
            "symbol": symbol,
            "status": "SKIPPED",
            "reason":
                "registro não atualizado",
        }

    return {
        "id": signal_id,
        "symbol": symbol,

        "scanner_price":
            float(old_price)
            if old_price is not None
            else None,

        "entry_price":
            real_price,

        "status":
            "UPDATED",
    }


# =========================================================
# RUN
# =========================================================

def update_pending_entries():

    signals = get_signals_to_update()

    print("")
    print("=" * 60)
    print(
        f"BOOSTER ENTRY UPDATER "
        f"V{UPDATER_VERSION}"
    )
    print("=" * 60)

    if not signals:

        print(
            "Nenhuma entrada pendente "
            "para atualizar."
        )

        return []

    print(
        f"Entradas encontradas: "
        f"{len(signals)}"
    )

    results = []

    for signal in signals:

        try:

            result = process_signal(
                signal
            )

            results.append(result)

            if (
                result.get("status")
                == "UPDATED"
            ):

                print(
                    "✅ Preço de entrada atualizado"
                )

                print(
                    f"   Scanner: "
                    f"{result['scanner_price']}"
                )

                print(
                    f"   Entrada: "
                    f"{result['entry_price']}"
                )

            else:

                print(
                    f"⚠️ {result}"
                )

        except Exception as exc:

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

            results.append(error)

            print(
                f"❌ {error}"
            )

    updated = sum(
        item.get("status") == "UPDATED"
        for item in results
    )

    pending = sum(
        item.get("status") == "PENDING"
        for item in results
    )

    errors = sum(
        item.get("status") == "ERROR"
        for item in results
    )

    print("")
    print("=" * 60)
    print("RESUMO")
    print("=" * 60)

    print(
        f"Atualizados: {updated}"
    )

    print(
        f"PENDING: {pending}"
    )

    print(
        f"ERROR: {errors}"
    )

    return results


if __name__ == "__main__":

    update_pending_entries()