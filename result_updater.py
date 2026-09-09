from __future__ import annotations

import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Dict, Optional, List


from database import supabase
from quotex_feed import fetch_1m_quotex


# =========================================================
# BOOSTER RESULT UPDATER V1.1
# =========================================================

UPDATER_VERSION = "1.2.0"

TZ = ZoneInfo("America/Sao_Paulo")

# Aguarda o candle de expiração estar fechado/disponível.
RESULT_DELAY_SECONDS = 120


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
# EXPIRY PRICE
# =========================================================

def get_expiry_price(
    symbol: str,
    expiry_time: datetime,
) -> Optional[float]:
    """
    Usa o feed da Quotex.

    Para uma expiração às 15:10, procura o candle M1
    iniciado às 15:09. O CLOSE desse candle representa
    o preço imediatamente anterior à expiração.
    """

    target_minute = (
        expiry_time - timedelta(minutes=1)
    ).replace(
        second=0,
        microsecond=0,
    )

    candles = fetch_1m_quotex(
        symbol=symbol,
        candle_count=2500,
    )

    for candle in candles:
        raw_datetime = candle.get("datetime")

        if not raw_datetime:
            continue

        candle_dt = parse_datetime(str(raw_datetime)).replace(
            second=0,
            microsecond=0,
        )

        if candle_dt == target_minute:
            try:
                return float(candle["close"])
            except (KeyError, TypeError, ValueError):
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

            # Mantemos o erro resumido no log.

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