import os
import requests
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

API_KEY = os.getenv("TWELVE_DATA_API_KEY")

if not API_KEY:
    raise ValueError("❌ TWELVE_DATA_API_KEY não encontrada no .env")


def get_candles(symbol="EUR/USD", interval="1min", outputsize=100):
    url = "https://api.twelvedata.com/time_series"

    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": API_KEY,
        "timezone": "America/Sao_Paulo"
    }

    print("📡 Buscando dados do mercado...")

    response = requests.get(
        url,
        params=params,
        timeout=20
    )

    response.raise_for_status()

    data = response.json()

    if data.get("status") == "error":
        raise RuntimeError(
            data.get("message", "Erro desconhecido da Twelve Data")
        )

    if "values" not in data:
        raise RuntimeError(
            f"Resposta inesperada da API: {data}"
        )

    return data


def main():

    print("\n🔥 BOOSTER MARKET COLLECTOR")
    print("=" * 60)

    try:

        data = get_candles(
            symbol="EUR/USD",
            interval="1min",
            outputsize=100
        )

        meta = data.get("meta", {})

        print("\n✅ FEED CONECTADO")
        print(f"📊 Ativo: {meta.get('symbol', 'EUR/USD')}")
        print("⏱️ Timeframe base: 1 minuto")
        print("🌎 Timezone: America/Sao_Paulo")

        print("=" * 60)

        # API normalmente retorna do mais recente
        # para o mais antigo.
        # Aqui colocamos em ordem cronológica.
        candles = list(reversed(data["values"]))

        formatted_candles = []

        for candle in candles:

            formatted = {
                "datetime": datetime.strptime(
                    candle["datetime"],
                    "%Y-%m-%d %H:%M:%S"
                ),
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"])
            }

            formatted_candles.append(formatted)

        print(f"\n🕯️ {len(formatted_candles)} candles carregados.")

        print("\n📌 ÚLTIMOS 10 CANDLES")
        print("-" * 60)

        for candle in formatted_candles[-10:]:

            direction = (
                "🟢"
                if candle["close"] >= candle["open"]
                else "🔴"
            )

            print(
                f"{direction} "
                f"{candle['datetime'].strftime('%H:%M')} | "
                f"O {candle['open']:.5f} | "
                f"H {candle['high']:.5f} | "
                f"L {candle['low']:.5f} | "
                f"C {candle['close']:.5f}"
            )

        print("\n" + "=" * 60)

        latest = formatted_candles[-1]

        print("🔥 ÚLTIMO CANDLE")
        print(f"⏰ {latest['datetime']}")
        print(f"OPEN : {latest['open']:.5f}")
        print(f"HIGH : {latest['high']:.5f}")
        print(f"LOW  : {latest['low']:.5f}")
        print(f"CLOSE: {latest['close']:.5f}")

        print("\n🚀 BOOSTER DATA FEED OK")

    except requests.exceptions.Timeout:

        print("\n❌ A API demorou demais para responder.")

    except requests.exceptions.RequestException as error:

        print("\n❌ Erro de conexão:")
        print(error)

    except Exception as error:

        print("\n❌ ERRO:")
        print(error)


if __name__ == "__main__":
    main()