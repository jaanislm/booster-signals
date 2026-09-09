from __future__ import annotations

import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Dict, Optional, List


from database import supabase
from quotex_feed import fetch_1m_quotex


# =========================================================
# BOOSTER ENTRY UPDATER V1.0
# =========================================================

UPDATER_VERSION = "1.1.0"

TZ = ZoneInfo("America/Sao_Paulo")

# Margem para o candle aparecer no feed
ENTRY_DELAY_SECONDS = 90


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
# PREÇO REAL DE ENTRADA
# =========================================================

def get_entry_price(
    symbol: str,
    entry_time: datetime,
) -> Optional[float]:
    """
    Usa o feed da Quotex.

    Se o Booster informou entrada às 21:15:00,
    procura o candle M1 iniciado às 21:15 e usa
    o OPEN desse candle como preço de referência.
    """

    target_minute = entry_time.replace(
        second=0,
        microsecond=0,
    )

    # O feed já mantém cache local; pedimos uma janela suficiente
    # para localizar entradas pendentes recentes.
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
                return float(candle["open"])
            except (KeyError, TypeError, ValueError):
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