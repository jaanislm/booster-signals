# ============================================================
# BOOSTER SIGNALS - BACKTEST V1.0
# ============================================================

from collector import get_candles
from engine import (
    parse_api_candles,
    aggregate,
    analyze_tf,
    build_signal,
)

from datetime import timedelta
import csv
import os


SYMBOL = "EUR/USD"
OUTPUTSIZE = 5000

RESULT_FILE = "backtest_results.csv"

# Precisamos de histórico suficiente antes de começar
# a avaliar cada ponto.
WARMUP_10M = 80
WARMUP_15M = 80
WARMUP_30M = 80
WARMUP_1H = 60


# ============================================================
# LOCALIZAR CANDLE
# ============================================================

def find_candle_at_or_after(candles, target_time):
    """
    Retorna o primeiro candle 1m cujo datetime seja
    igual ou posterior ao horário solicitado.
    """

    for candle in candles:
        if candle["datetime"] >= target_time:
            return candle

    return None


# ============================================================
# RESULTADO BINÁRIO
# ============================================================

def binary_result(entry_price, exit_price, direction):

    if direction == "BUY":

        if exit_price > entry_price:
            return "WIN"

        elif exit_price < entry_price:
            return "LOSS"

        return "DRAW"

    if direction == "SELL":

        if exit_price < entry_price:
            return "WIN"

        elif exit_price > entry_price:
            return "LOSS"

        return "DRAW"

    return "INVALID"


# ============================================================
# CONSTRUIR TIMEFRAMES ATÉ UM DETERMINADO MOMENTO
# ============================================================

def build_tf_until(base, current_time):

    historical = [
        candle
        for candle in base
        if candle["datetime"] < current_time
    ]

    tf10 = aggregate(historical, 10)
    tf15 = aggregate(historical, 15)
    tf30 = aggregate(historical, 30)
    tf60 = aggregate(historical, 60)

    return tf10, tf15, tf30, tf60


# ============================================================
# SALVAR CSV
# ============================================================

def save_results(rows):

    fields = [
        "signal_time",
        "symbol",

        "direction",
        "grade",

        "entry_price",

        "buy_score",
        "sell_score",
        "edge",

        "trend_10m",
        "trend_15m",
        "trend_30m",
        "trend_1h",

        "adx_10m",
        "adx_15m",

        "expiry_10m_price",
        "result_10m",

        "expiry_15m_price",
        "result_15m"
    ]

    with open(
        RESULT_FILE,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fields
        )

        writer.writeheader()
        writer.writerows(rows)


# ============================================================
# ESTATÍSTICAS
# ============================================================

def percentage(wins, losses):

    total = wins + losses

    if total == 0:
        return 0

    return wins / total * 100


def stats(rows, result_column):

    wins = sum(
        1 for row in rows
        if row[result_column] == "WIN"
    )

    losses = sum(
        1 for row in rows
        if row[result_column] == "LOSS"
    )

    draws = sum(
        1 for row in rows
        if row[result_column] == "DRAW"
    )

    return {
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "rate": percentage(
            wins,
            losses
        )
    }


def print_group(title, rows):

    if not rows:
        print(
            f"{title:<15} | "
            f"0 sinais"
        )
        return

    s10 = stats(
        rows,
        "result_10m"
    )

    s15 = stats(
        rows,
        "result_15m"
    )

    print(
        f"{title:<15} | "
        f"{len(rows):>4} sinais | "
        f"10M {s10['rate']:>6.2f}% "
        f"({s10['wins']}W/{s10['losses']}L) | "
        f"15M {s15['rate']:>6.2f}% "
        f"({s15['wins']}W/{s15['losses']}L)"
    )


# ============================================================
# BACKTEST
# ============================================================

def main():

    print()
    print("🔥 BOOSTER BACKTEST V1.0")
    print("=" * 85)

    print(
        f"📡 Buscando {OUTPUTSIZE} candles "
        f"de {SYMBOL}..."
    )

    data = get_candles(
        symbol=SYMBOL,
        interval="1min",
        outputsize=OUTPUTSIZE
    )

    base = parse_api_candles(data)

    print(
        f"✅ {len(base)} candles carregados"
    )

    # --------------------------------------------------------
    # GRADE 10M COMPLETA
    #
    # Cada ponto de avaliação ocorre depois do fechamento
    # de um candle de 10 minutos.
    # --------------------------------------------------------

    full_10m = aggregate(
        base,
        10
    )

    print(
        f"🧱 {len(full_10m)} candles 10M construídos"
    )

    results = []

    # Evita registrar o mesmo estado repetidamente.
    last_signature = None

    print()
    print("🧠 Executando backtest...")
    print()

    for index in range(
        WARMUP_10M,
        len(full_10m)
    ):

        candle10 = full_10m[index]

        # O bucket 10M começa nesse horário.
        # Portanto a análise ocorre após seu fechamento.
        signal_time = (
            candle10["datetime"]
            + timedelta(minutes=10)
        )

        # Precisamos de 15 minutos futuros para avaliar
        # ambas as expirações.
        if (
            signal_time
            + timedelta(minutes=15)
            > base[-1]["datetime"]
        ):
            break

        try:

            (
                candles10,
                candles15,
                candles30,
                candles60
            ) = build_tf_until(
                base,
                signal_time
            )

            if (
                len(candles10) < WARMUP_10M
                or len(candles15) < WARMUP_15M
                or len(candles30) < WARMUP_30M
                or len(candles60) < WARMUP_1H
            ):
                continue

            tf10 = analyze_tf(
                "10M",
                candles10
            )

            tf15 = analyze_tf(
                "15M",
                candles15
            )

            tf30 = analyze_tf(
                "30M",
                candles30
            )

            tf1h = analyze_tf(
                "1H",
                candles60
            )

            signal = build_signal(
                tf10,
                tf15,
                tf30,
                tf1h
            )

        except Exception:
            continue

        # Só queremos os sinais efetivamente
        # liberados pelo Booster.
        if signal["grade"] not in (
            "A",
            "A+"
        ):
            continue

        if signal["direction"] not in (
            "BUY",
            "SELL"
        ):
            continue

        # ----------------------------------------------------
        # ENTRADA
        #
        # Entrada no primeiro candle 1M disponível a partir
        # do horário em que o sinal ficou conhecido.
        # ----------------------------------------------------

        entry_candle = find_candle_at_or_after(
            base,
            signal_time
        )

        if entry_candle is None:
            continue

        entry_price = entry_candle["open"]

        # ----------------------------------------------------
        # EXPIRAÇÃO 10M
        # ----------------------------------------------------

        expiry10_time = (
            signal_time
            + timedelta(minutes=10)
        )

        expiry10_candle = find_candle_at_or_after(
            base,
            expiry10_time
        )

        if expiry10_candle is None:
            continue

        exit10 = expiry10_candle["open"]

        result10 = binary_result(
            entry_price,
            exit10,
            signal["direction"]
        )

        # ----------------------------------------------------
        # EXPIRAÇÃO 15M
        # ----------------------------------------------------

        expiry15_time = (
            signal_time
            + timedelta(minutes=15)
        )

        expiry15_candle = find_candle_at_or_after(
            base,
            expiry15_time
        )

        if expiry15_candle is None:
            continue

        exit15 = expiry15_candle["open"]

        result15 = binary_result(
            entry_price,
            exit15,
            signal["direction"]
        )

        # ----------------------------------------------------
        # EVITAR SINAIS DUPLICADOS
        # ----------------------------------------------------

        signature = (
            signal_time,
            signal["direction"],
            signal["grade"]
        )

        if signature == last_signature:
            continue

        last_signature = signature

        # ----------------------------------------------------
        # REGISTRAR
        # ----------------------------------------------------

        row = {

            "signal_time":
                signal_time.isoformat(),

            "symbol":
                SYMBOL,

            "direction":
                signal["direction"],

            "grade":
                signal["grade"],

            "entry_price":
                round(entry_price, 6),

            "buy_score":
                signal["buy_score"],

            "sell_score":
                signal["sell_score"],

            "edge":
                signal["edge"],

            "trend_10m":
                tf10["trend"],

            "trend_15m":
                tf15["trend"],

            "trend_30m":
                tf30["trend"],

            "trend_1h":
                tf1h["trend"],

            "adx_10m":
                round(
                    tf10["adx"],
                    2
                ),

            "adx_15m":
                round(
                    tf15["adx"],
                    2
                ),

            "expiry_10m_price":
                round(exit10, 6),

            "result_10m":
                result10,

            "expiry_15m_price":
                round(exit15, 6),

            "result_15m":
                result15
        }

        results.append(row)

        icon10 = (
            "✅"
            if result10 == "WIN"
            else "❌"
        )

        icon15 = (
            "✅"
            if result15 == "WIN"
            else "❌"
        )

        print(
            f"{signal_time} | "
            f"{signal['grade']:<2} | "
            f"{signal['direction']:<4} | "
            f"10M {icon10} {result10:<4} | "
            f"15M {icon15} {result15:<4}"
        )

    # ========================================================
    # SALVAR
    # ========================================================

    save_results(
        results
    )

    # ========================================================
    # RESULTADO
    # ========================================================

    print()
    print("=" * 85)
    print("📊 RESULTADO DO BOOSTER")
    print("=" * 85)

    print(
        f"\nTOTAL DE SINAIS: "
        f"{len(results)}"
    )

    if not results:

        print()
        print(
            "Nenhum A/A+ encontrado "
            "neste histórico."
        )

        print(
            "Não altere os filtros ainda."
        )

        print()
        print(
            f"💾 {RESULT_FILE} criado."
        )

        return

    print()

    print_group(
        "GERAL",
        results
    )

    print()
    print("-" * 85)

    # --------------------------------------------------------
    # GRADE
    # --------------------------------------------------------

    a_plus = [
        r for r in results
        if r["grade"] == "A+"
    ]

    a_grade = [
        r for r in results
        if r["grade"] == "A"
    ]

    print_group(
        "A+",
        a_plus
    )

    print_group(
        "A",
        a_grade
    )

    print()
    print("-" * 85)

    # --------------------------------------------------------
    # DIREÇÃO
    # --------------------------------------------------------

    buys = [
        r for r in results
        if r["direction"] == "BUY"
    ]

    sells = [
        r for r in results
        if r["direction"] == "SELL"
    ]

    print_group(
        "BUY",
        buys
    )

    print_group(
        "SELL",
        sells
    )

    # --------------------------------------------------------
    # MELHOR EXPIRAÇÃO
    # --------------------------------------------------------

    total10 = stats(
        results,
        "result_10m"
    )

    total15 = stats(
        results,
        "result_15m"
    )

    print()
    print("=" * 85)
    print("⏱️ COMPARAÇÃO DE EXPIRAÇÃO")
    print("=" * 85)

    print(
        f"10 minutos : "
        f"{total10['rate']:.2f}% "
        f"| {total10['wins']} WIN "
        f"| {total10['losses']} LOSS "
        f"| {total10['draws']} DRAW"
    )

    print(
        f"15 minutos : "
        f"{total15['rate']:.2f}% "
        f"| {total15['wins']} WIN "
        f"| {total15['losses']} LOSS "
        f"| {total15['draws']} DRAW"
    )

    if total10["rate"] > total15["rate"]:

        print(
            "\n🏆 Neste histórico, "
            "10 minutos teve melhor resultado."
        )

    elif total15["rate"] > total10["rate"]:

        print(
            "\n🏆 Neste histórico, "
            "15 minutos teve melhor resultado."
        )

    else:

        print(
            "\n⚖️ As duas expirações empataram."
        )

    print()
    print("=" * 85)

    print(
        f"💾 Resultado completo salvo em "
        f"{RESULT_FILE}"
    )

    print(
        "\n⚠️ Resultado histórico não garante "
        "desempenho futuro."
    )

    print(
        "🔥 BACKTEST FINALIZADO"
    )


if __name__ == "__main__":
    main()