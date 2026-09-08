# ============================================================
# BOOSTER MARKET SCANNER V1.1
# Multiativos + ranking + melhor oportunidade
# ============================================================

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from zoneinfo import ZoneInfo

from collector import get_candles
from engine import (
    parse_api_candles,
    aggregate,
    analyze_tf,
    build_signal,
)

TZ = ZoneInfo("America/Sao_Paulo")

ASSETS = [
    "EUR/USD",
    "GBP/USD",
    "EUR/JPY",
    "EUR/GBP",
    "GBP/JPY",
    "AUD/USD",
    "AUD/JPY",
    "USD/JPY",
]

OUTPUTSIZE = 5000
MAX_WORKERS = 4


def now_sp():
    return datetime.now(TZ)


def analyze_asset(symbol):
    try:
        print(f"🔎 Analisando {symbol}...")

        data = get_candles(
            symbol=symbol,
            interval="1min",
            outputsize=OUTPUTSIZE
        )

        base = parse_api_candles(data)

        if len(base) < 1000:
            return {
                "symbol": symbol,
                "status": "ERROR",
                "error": "Histórico insuficiente"
            }

        candles10 = aggregate(base, 10)
        candles15 = aggregate(base, 15)
        candles30 = aggregate(base, 30)
        candles60 = aggregate(base, 60)

        if (
            len(candles10) < 50
            or len(candles15) < 50
            or len(candles30) < 50
            or len(candles60) < 50
        ):
            return {
                "symbol": symbol,
                "status": "ERROR",
                "error": "Timeframes insuficientes"
            }

        tf10 = analyze_tf("10M", candles10)
        tf15 = analyze_tf("15M", candles15)
        tf30 = analyze_tf("30M", candles30)
        tf1h = analyze_tf("1H", candles60)

        signal = build_signal(
            tf10,
            tf15,
            tf30,
            tf1h
        )

        grade = signal["grade"]

        if grade == "A+":
            grade_points = 30
        elif grade == "A":
            grade_points = 20
        else:
            grade_points = 0

        edge = signal["edge"]

        adx15 = tf15["adx"]
        adx10 = tf10["adx"]

        # Score apenas para RANKING.
        # NÃO representa porcentagem de acerto.
        ranking_score = (
            grade_points
            + edge
            + min(adx15, 40) / 4
            + min(adx10, 40) / 8
        )

        return {
            "symbol": symbol,
            "market_type": "NORMAL",
            "status": "OK",

            "direction": signal["direction"],
            "grade": grade,
            "expiry": signal["expiry"],

            "buy_score": signal["buy_score"],
            "sell_score": signal["sell_score"],
            "edge": edge,

            "ranking_score": round(ranking_score, 2),

            "price": round(tf10["price"], 6),

            "trends": {
                "10m": tf10["trend"],
                "15m": tf15["trend"],
                "30m": tf30["trend"],
                "1h": tf1h["trend"],
            },

            "adx": {
                "10m": round(tf10["adx"], 2),
                "15m": round(tf15["adx"], 2),
            },

            "confirmations": signal["reasons"],
            "vetoes": signal["vetoes"],

            "signal_time": tf10["datetime"].isoformat(),
        }

    except Exception as error:
        return {
            "symbol": symbol,
            "status": "ERROR",
            "error": str(error)
        }


def scan_market():

    started_at = now_sp()

    print()
    print("=" * 70)
    print("🔥 BOOSTER MARKET SCANNER V1.1")
    print("=" * 70)
    print(
        f"⏰ {started_at.strftime('%d/%m/%Y %H:%M:%S')}"
    )
    print(f"📊 {len(ASSETS)} ativos")
    print("=" * 70)
    print()

    results = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(analyze_asset, symbol): symbol
            for symbol in ASSETS
        }

        for future in as_completed(futures):
            results.append(future.result())

    valid = [
        result
        for result in results
        if result.get("status") == "OK"
    ]

    valid.sort(
        key=lambda item: item["ranking_score"],
        reverse=True
    )

    opportunities = [
        item
        for item in valid
        if item["grade"] in ("A", "A+")
        and item["direction"] in ("BUY", "SELL")
    ]

    best = opportunities[0] if opportunities else None

    errors = [
        result
        for result in results
        if result.get("status") == "ERROR"
    ]

    return {
        "scanned_at": now_sp().isoformat(),
        "assets_scanned": len(ASSETS),
        "assets_valid": len(valid),
        "opportunities": len(opportunities),
        "best": best,
        "ranking": valid,
        "errors": errors,
    }


if __name__ == "__main__":

    result = scan_market()

    print()
    print("=" * 70)
    print("📊 RANKING")
    print("=" * 70)

    for position, asset in enumerate(
        result["ranking"],
        start=1
    ):
        print()
        print(f"{position}. {asset['symbol']}")
        print(f"   Direção: {asset['direction']}")
        print(f"   Grade: {asset['grade']}")
        print(f"   Edge: {asset['edge']}")
        print(f"   Ranking: {asset['ranking_score']}")
        print(f"   ADX 10M: {asset['adx']['10m']}")
        print(f"   ADX 15M: {asset['adx']['15m']}")

    print()
    print("=" * 70)

    if result["best"]:

        best = result["best"]

        print("🚨 MELHOR OPORTUNIDADE")
        print("=" * 70)

        print(f"ATIVO: {best['symbol']}")
        print(f"DIREÇÃO: {best['direction']}")
        print(f"GRADE: {best['grade']}")
        print(f"RANKING: {best['ranking_score']}")
        print(f"PREÇO: {best['price']}")

        print()
        print("CONFIRMAÇÕES:")

        for confirmation in best["confirmations"]:
            print(f"✓ {confirmation}")

    else:
        print(
            "⏳ Nenhuma oportunidade A/A+ encontrada agora."
        )

    print("=" * 70)