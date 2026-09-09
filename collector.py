from quotex_feed import fetch_1m_quotex


def get_candles(
    symbol="EUR/USD",
    interval="1min",
    outputsize=100,
):
    """
    Compatibilidade com o código antigo do Booster.
    Fonte atual: Quotex.
    """

    if interval != "1min":
        raise ValueError(
            "collector.py recebe somente M1. "
            "Outros timeframes são agregados pelo scanner."
        )

    candles = fetch_1m_quotex(
        symbol=symbol,
        candle_count=outputsize,
    )

    return candles


def main():
    print("\n🔥 BOOSTER MARKET COLLECTOR")
    print("=" * 60)
    print("📡 Fonte: QUOTEX")

    try:
        candles = get_candles(
            symbol="EUR/USD",
            outputsize=100,
        )

        print(f"✅ {len(candles)} candles carregados")
        print("🚀 QUOTEX DATA FEED OK")

        if candles:
            print("Último candle:")
            print(candles[-1])

    except Exception as error:
        print(f"❌ ERRO: {error}")


if __name__ == "__main__":
    main()