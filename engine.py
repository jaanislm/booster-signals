from collector import get_candles
from datetime import datetime
import csv
import os
import math


# ============================================================
# BOOSTER ENGINE V1.0
# MOTOR CONSOLIDADO
# ============================================================

SYMBOL = "EUR/USD"

EMA_PERIOD = 9
SMA_PERIOD = 20
ATR_PERIOD = 14
ADX_PERIOD = 14

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

MAX_DISTANCE_ATR = 1.80
EXPLOSIVE_ATR = 1.80
ADX_MIN = 20

LOG_FILE = "signals.csv"


# ============================================================
# UTIL
# ============================================================

def safe_div(a, b):
    if b == 0:
        return 0.0
    return a / b


def parse_api_candles(data):
    values = list(reversed(data["values"]))
    result = []

    for c in values:
        result.append({
            "datetime": datetime.strptime(
                c["datetime"],
                "%Y-%m-%d %H:%M:%S"
            ),
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"])
        })

    return result


# ============================================================
# AGREGAÇÃO
# ============================================================

def aggregate(candles, minutes):
    groups = {}

    for c in candles:
        dt = c["datetime"]

        total_minutes = dt.hour * 60 + dt.minute
        bucket_total = (total_minutes // minutes) * minutes

        bucket_hour = (bucket_total // 60) % 24
        bucket_minute = bucket_total % 60

        bucket = dt.replace(
            hour=bucket_hour,
            minute=bucket_minute,
            second=0,
            microsecond=0
        )

        groups.setdefault(bucket, []).append(c)

    result = []

    for bucket in sorted(groups):
        group = groups[bucket]

        # Descarta candle incompleto
        if len(group) != minutes:
            continue

        result.append({
            "datetime": bucket,
            "open": group[0]["open"],
            "high": max(x["high"] for x in group),
            "low": min(x["low"] for x in group),
            "close": group[-1]["close"]
        })

    return result


# ============================================================
# SMA
# ============================================================

def sma_series(values, period):
    result = [None] * len(values)

    for i in range(period - 1, len(values)):
        result[i] = sum(
            values[i - period + 1:i + 1]
        ) / period

    return result


# ============================================================
# EMA
# ============================================================

def ema_series(values, period):
    result = [None] * len(values)

    if len(values) < period:
        return result

    seed = sum(values[:period]) / period
    result[period - 1] = seed

    alpha = 2 / (period + 1)
    previous = seed

    for i in range(period, len(values)):
        current = (
            values[i] * alpha
            + previous * (1 - alpha)
        )

        result[i] = current
        previous = current

    return result


# ============================================================
# WILDER RMA
# ============================================================

def rma_series(values, period):
    result = [None] * len(values)

    if len(values) < period:
        return result

    seed = sum(values[:period]) / period
    result[period - 1] = seed

    previous = seed

    for i in range(period, len(values)):
        current = (
            previous * (period - 1)
            + values[i]
        ) / period

        result[i] = current
        previous = current

    return result


# ============================================================
# ATR / DI / ADX
# ============================================================

def dmi_atr(candles, period=14):
    n = len(candles)

    tr = [0.0] * n
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n

    for i in range(n):
        high = candles[i]["high"]
        low = candles[i]["low"]

        if i == 0:
            tr[i] = high - low
            continue

        prev_high = candles[i - 1]["high"]
        prev_low = candles[i - 1]["low"]
        prev_close = candles[i - 1]["close"]

        tr[i] = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )

        up = high - prev_high
        down = prev_low - low

        plus_dm[i] = (
            up if up > down and up > 0 else 0.0
        )

        minus_dm[i] = (
            down if down > up and down > 0 else 0.0
        )

    atr = rma_series(tr, period)
    plus_rma = rma_series(plus_dm, period)
    minus_rma = rma_series(minus_dm, period)

    plus_di = [None] * n
    minus_di = [None] * n
    dx = [None] * n

    for i in range(n):
        if atr[i] is None or atr[i] == 0:
            continue

        plus_di[i] = 100 * safe_div(
            plus_rma[i], atr[i]
        )

        minus_di[i] = 100 * safe_div(
            minus_rma[i], atr[i]
        )

        denominator = plus_di[i] + minus_di[i]

        if denominator > 0:
            dx[i] = (
                100
                * abs(plus_di[i] - minus_di[i])
                / denominator
            )

    # ADX sobre os DX válidos
    adx = [None] * n

    valid_indices = [
        i for i, value in enumerate(dx)
        if value is not None
    ]

    if len(valid_indices) >= period:
        first_indices = valid_indices[:period]

        seed = sum(
            dx[i] for i in first_indices
        ) / period

        seed_index = first_indices[-1]
        adx[seed_index] = seed
        previous = seed

        for i in valid_indices[period:]:
            current = (
                previous * (period - 1)
                + dx[i]
            ) / period

            adx[i] = current
            previous = current

    return atr, plus_di, minus_di, adx


# ============================================================
# MACD
# ============================================================

def macd(candles):
    closes = [c["close"] for c in candles]

    fast = ema_series(closes, MACD_FAST)
    slow = ema_series(closes, MACD_SLOW)

    macd_line = [None] * len(closes)

    for i in range(len(closes)):
        if fast[i] is not None and slow[i] is not None:
            macd_line[i] = fast[i] - slow[i]

    valid = [
        value for value in macd_line
        if value is not None
    ]

    signal_valid = ema_series(
        valid,
        MACD_SIGNAL
    )

    signal = [None] * len(closes)

    valid_position = 0

    for i in range(len(closes)):
        if macd_line[i] is not None:
            signal[i] = signal_valid[valid_position]
            valid_position += 1

    hist = [None] * len(closes)

    for i in range(len(closes)):
        if (
            macd_line[i] is not None
            and signal[i] is not None
        ):
            hist[i] = (
                macd_line[i] - signal[i]
            )

    return macd_line, signal, hist


# ============================================================
# FRACTAIS CONFIRMADOS
# ============================================================

def last_confirmed_fractals(candles):
    fractal_high = None
    fractal_low = None

    # Os dois candles à direita precisam existir.
    for i in range(2, len(candles) - 2):
        h = candles[i]["high"]
        l = candles[i]["low"]

        is_high = (
            h > candles[i - 1]["high"]
            and h > candles[i - 2]["high"]
            and h > candles[i + 1]["high"]
            and h > candles[i + 2]["high"]
        )

        is_low = (
            l < candles[i - 1]["low"]
            and l < candles[i - 2]["low"]
            and l < candles[i + 1]["low"]
            and l < candles[i + 2]["low"]
        )

        if is_high:
            fractal_high = h

        if is_low:
            fractal_low = l

    return fractal_high, fractal_low


# ============================================================
# PRICE ACTION
# ============================================================

def price_action(candles):
    c = candles[-1]
    p = candles[-2]

    body = abs(c["close"] - c["open"])
    candle_range = c["high"] - c["low"]

    upper_wick = (
        c["high"]
        - max(c["open"], c["close"])
    )

    lower_wick = (
        min(c["open"], c["close"])
        - c["low"]
    )

    bullish_rejection = (
        lower_wick > body * 1.2
        and c["close"] > c["open"]
    )

    bearish_rejection = (
        upper_wick > body * 1.2
        and c["close"] < c["open"]
    )

    bullish_engulf = (
        c["close"] > c["open"]
        and p["close"] < p["open"]
        and c["open"] <= p["close"]
        and c["close"] >= p["open"]
    )

    bearish_engulf = (
        c["close"] < c["open"]
        and p["close"] > p["open"]
        and c["open"] >= p["close"]
        and c["close"] <= p["open"]
    )

    return {
        "body": body,
        "range": candle_range,
        "bull_rejection": bullish_rejection,
        "bear_rejection": bearish_rejection,
        "bull_engulf": bullish_engulf,
        "bear_engulf": bearish_engulf
    }


# ============================================================
# ANALISAR TIMEFRAME
# ============================================================

def analyze_tf(name, candles):
    if len(candles) < 60:
        raise ValueError(
            f"{name}: histórico insuficiente "
            f"({len(candles)} candles)"
        )

    closes = [c["close"] for c in candles]

    ema9 = ema_series(closes, EMA_PERIOD)
    sma20 = sma_series(closes, SMA_PERIOD)

    atr, plus_di, minus_di, adx = dmi_atr(
        candles,
        ADX_PERIOD
    )

    macd_line, macd_signal, hist = macd(
        candles
    )

    i = len(candles) - 1
    previous = i - 1

    required = [
        ema9[i],
        sma20[i],
        atr[i],
        plus_di[i],
        minus_di[i],
        adx[i],
        hist[i]
    ]

    if any(x is None for x in required):
        raise ValueError(
            f"{name}: indicadores não estabilizados"
        )

    price = closes[i]

    ema_up = (
        ema9[previous] is not None
        and ema9[i] > ema9[previous]
    )

    ema_down = (
        ema9[previous] is not None
        and ema9[i] < ema9[previous]
    )

    hist_up = (
        hist[previous] is not None
        and hist[i] > hist[previous]
    )

    hist_down = (
        hist[previous] is not None
        and hist[i] < hist[previous]
    )

    bull_trend = (
        ema9[i] > sma20[i]
        and price > ema9[i]
        and ema_up
    )

    bear_trend = (
        ema9[i] < sma20[i]
        and price < ema9[i]
        and ema_down
    )

    if bull_trend:
        trend = "ALTA"
    elif bear_trend:
        trend = "BAIXA"
    else:
        trend = "NEUTRO"

    dmi_bull = plus_di[i] > minus_di[i]
    dmi_bear = minus_di[i] > plus_di[i]

    impulse_bull = (
        ema_up
        and hist_up
    )

    impulse_bear = (
        ema_down
        and hist_down
    )

    pa = price_action(candles)

    fractal_high, fractal_low = (
        last_confirmed_fractals(candles)
    )

    breakout_bull = (
        fractal_high is not None
        and price > fractal_high
    )

    breakout_bear = (
        fractal_low is not None
        and price < fractal_low
    )

    distance = abs(
        price - ema9[i]
    )

    distance_atr = safe_div(
        distance,
        atr[i]
    )

    extended = (
        distance_atr > MAX_DISTANCE_ATR
    )

    explosive = (
        pa["range"]
        > atr[i] * EXPLOSIVE_ATR
    )

    # Compressão relativa das médias
    ma_distance = abs(
        ema9[i] - sma20[i]
    )

    compressed = (
        ma_distance
        < atr[i] * 0.10
    )

    adx_ok = adx[i] >= ADX_MIN

    return {
        "name": name,
        "datetime": candles[i]["datetime"],
        "price": price,

        "ema9": ema9[i],
        "sma20": sma20[i],

        "atr": atr[i],
        "adx": adx[i],
        "plus_di": plus_di[i],
        "minus_di": minus_di[i],

        "macd": macd_line[i],
        "hist": hist[i],

        "trend": trend,

        "dmi_bull": dmi_bull,
        "dmi_bear": dmi_bear,

        "impulse_bull": impulse_bull,
        "impulse_bear": impulse_bear,

        "bull_rejection": pa["bull_rejection"],
        "bear_rejection": pa["bear_rejection"],

        "bull_engulf": pa["bull_engulf"],
        "bear_engulf": pa["bear_engulf"],

        "breakout_bull": breakout_bull,
        "breakout_bear": breakout_bear,

        "fractal_high": fractal_high,
        "fractal_low": fractal_low,

        "distance_atr": distance_atr,

        "extended": extended,
        "explosive": explosive,
        "compressed": compressed,

        "adx_ok": adx_ok
    }


# ============================================================
# SCORE
# ============================================================

def build_signal(tf10, tf15, tf30, tf1h):
    buy = 0
    sell = 0

    buy_reasons = []
    sell_reasons = []

    # ========================================================
    # MACRO — 30M
    # ========================================================

    if tf30["trend"] == "ALTA":
        buy += 2
        buy_reasons.append("30M alta")

    elif tf30["trend"] == "BAIXA":
        sell += 2
        sell_reasons.append("30M baixa")

    # 1H é contexto, não veto absoluto
    if tf1h["trend"] == "ALTA":
        buy += 1
        buy_reasons.append("1H alta")

    elif tf1h["trend"] == "BAIXA":
        sell += 1
        sell_reasons.append("1H baixa")

    # ========================================================
    # ESTRUTURA — 15M
    # ========================================================

    if tf15["trend"] == "ALTA":
        buy += 3
        buy_reasons.append("15M alta")

    elif tf15["trend"] == "BAIXA":
        sell += 3
        sell_reasons.append("15M baixa")

    # ========================================================
    # TIMING — 10M
    # ========================================================

    if tf10["trend"] == "ALTA":
        buy += 2
        buy_reasons.append("10M alta")

    elif tf10["trend"] == "BAIXA":
        sell += 2
        sell_reasons.append("10M baixa")

    # ========================================================
    # ADX + DMI
    # ========================================================

    if tf15["adx_ok"]:
        if tf15["dmi_bull"]:
            buy += 2
            buy_reasons.append("DI+ dominante")

        elif tf15["dmi_bear"]:
            sell += 2
            sell_reasons.append("DI- dominante")

    if tf10["adx_ok"]:
        if tf10["dmi_bull"]:
            buy += 1
            buy_reasons.append("10M DMI alta")

        elif tf10["dmi_bear"]:
            sell += 1
            sell_reasons.append("10M DMI baixa")

    # ========================================================
    # IMPULSO
    # ========================================================

    if tf15["impulse_bull"]:
        buy += 2
        buy_reasons.append("impulso comprador")

    if tf15["impulse_bear"]:
        sell += 2
        sell_reasons.append("impulso vendedor")

    # ========================================================
    # PRICE ACTION 10M
    # ========================================================

    if tf10["bull_rejection"]:
        buy += 1
        buy_reasons.append("rejeição compradora")

    if tf10["bear_rejection"]:
        sell += 1
        sell_reasons.append("rejeição vendedora")

    if tf10["bull_engulf"]:
        buy += 1
        buy_reasons.append("engolfo comprador")

    if tf10["bear_engulf"]:
        sell += 1
        sell_reasons.append("engolfo vendedor")

    if tf10["breakout_bull"]:
        buy += 1
        buy_reasons.append("rompimento fractal")

    if tf10["breakout_bear"]:
        sell += 1
        sell_reasons.append("rompimento fractal")

    # ========================================================
    # VETOS DE SEGURANÇA
    # ========================================================

    vetoes = []

    if tf10["extended"]:
        vetoes.append("preço esticado da EMA")

    if tf10["explosive"]:
        vetoes.append("candle explosivo")

    if tf10["compressed"]:
        vetoes.append("médias comprimidas")

    # ADX muito fraco no timeframe operacional
    if tf15["adx"] < ADX_MIN:
        vetoes.append("ADX 15M fraco")

    # ========================================================
    # DECISÃO
    # ========================================================

    direction = None
    score = 0
    reasons = []

    if buy > sell:
        direction = "BUY"
        score = buy
        reasons = buy_reasons

    elif sell > buy:
        direction = "SELL"
        score = sell
        reasons = sell_reasons

    # Diferença entre lados
    edge = abs(buy - sell)

    # Conflito muito grande
    if edge < 3:
        vetoes.append("direção sem vantagem suficiente")

    # ========================================================
    # GRADE
    # ========================================================

    if direction is None or vetoes:
        grade = "BLOQUEADO"

    elif score >= 12 and edge >= 7:
        grade = "A+"

    elif score >= 9 and edge >= 5:
        grade = "A"

    else:
        grade = "BLOQUEADO"

    # ========================================================
    # EXPIRAÇÃO CANDIDATA
    # NÃO é previsão garantida.
    # ========================================================

    expiry = None

    if grade == "A+":
        expiry = "15m"

    elif grade == "A":
        expiry = "10m"

    return {
        "direction": direction,
        "grade": grade,
        "expiry": expiry,

        "buy_score": buy,
        "sell_score": sell,
        "edge": edge,

        "reasons": reasons,
        "vetoes": vetoes
    }


# ============================================================
# LOG
# ============================================================

def save_signal(signal, tf10, tf15, tf30, tf1h):
    if signal["grade"] not in ("A", "A+"):
        return

    exists = os.path.exists(LOG_FILE)

    fields = [
        "timestamp",
        "symbol",
        "direction",
        "grade",
        "expiry",

        "price",

        "buy_score",
        "sell_score",
        "edge",

        "trend_10m",
        "trend_15m",
        "trend_30m",
        "trend_1h",

        "adx_10m",
        "adx_15m",

        "di_plus_15m",
        "di_minus_15m",

        "atr_10m",

        "ema9_10m",
        "sma20_10m",

        "distance_atr",

        "result"
    ]

    row = {
        "timestamp": tf10["datetime"].isoformat(),
        "symbol": SYMBOL,
        "direction": signal["direction"],
        "grade": signal["grade"],
        "expiry": signal["expiry"],

        "price": tf10["price"],

        "buy_score": signal["buy_score"],
        "sell_score": signal["sell_score"],
        "edge": signal["edge"],

        "trend_10m": tf10["trend"],
        "trend_15m": tf15["trend"],
        "trend_30m": tf30["trend"],
        "trend_1h": tf1h["trend"],

        "adx_10m": round(tf10["adx"], 2),
        "adx_15m": round(tf15["adx"], 2),

        "di_plus_15m": round(
            tf15["plus_di"], 2
        ),

        "di_minus_15m": round(
            tf15["minus_di"], 2
        ),

        "atr_10m": tf10["atr"],

        "ema9_10m": tf10["ema9"],
        "sma20_10m": tf10["sma20"],

        "distance_atr": round(
            tf10["distance_atr"], 3
        ),

        "result": ""
    }

    # Evita duplicar exatamente o mesmo sinal
    if exists:
        try:
            with open(
                LOG_FILE,
                "r",
                newline="",
                encoding="utf-8"
            ) as file:
                rows = list(csv.DictReader(file))

                if rows:
                    last = rows[-1]

                    if (
                        last.get("timestamp")
                        == row["timestamp"]
                        and last.get("symbol")
                        == row["symbol"]
                        and last.get("direction")
                        == row["direction"]
                    ):
                        return

        except Exception:
            pass

    with open(
        LOG_FILE,
        "a",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fields
        )

        if not exists:
            writer.writeheader()

        writer.writerow(row)


# ============================================================
# PRINT
# ============================================================

def print_tf(tf):
    icon = {
        "ALTA": "🟢",
        "BAIXA": "🔴",
        "NEUTRO": "⚪"
    }.get(tf["trend"], "⚪")

    print(
        f"{tf['name']:<4} "
        f"{icon} {tf['trend']:<7} | "
        f"ADX {tf['adx']:>5.1f} | "
        f"DI+ {tf['plus_di']:>5.1f} | "
        f"DI- {tf['minus_di']:>5.1f} | "
        f"ATR {tf['atr']:.5f}"
    )


# ============================================================
# MAIN
# ============================================================

def main():
    print()
    print("🔥 BOOSTER SIGNALS ENGINE V1.0")
    print("=" * 78)

    try:
        print("📡 Carregando EUR/USD 1m...")

        data = get_candles(
            symbol=SYMBOL,
            interval="1min",
            outputsize=5000
        )

        base = parse_api_candles(data)

        print(
            f"✅ {len(base)} candles 1m recebidos"
        )

        print("🧱 Construindo timeframes...")

        candles_10 = aggregate(base, 10)
        candles_15 = aggregate(base, 15)
        candles_30 = aggregate(base, 30)
        candles_60 = aggregate(base, 60)

        print(
            f"10M: {len(candles_10)} | "
            f"15M: {len(candles_15)} | "
            f"30M: {len(candles_30)} | "
            f"1H: {len(candles_60)}"
        )

        tf10 = analyze_tf(
            "10M",
            candles_10
        )

        tf15 = analyze_tf(
            "15M",
            candles_15
        )

        tf30 = analyze_tf(
            "30M",
            candles_30
        )

        tf1h = analyze_tf(
            "1H",
            candles_60
        )

        print()
        print("=" * 78)
        print("📊 MERCADO")
        print("=" * 78)

        print_tf(tf10)
        print_tf(tf15)
        print_tf(tf30)
        print_tf(tf1h)

        signal = build_signal(
            tf10,
            tf15,
            tf30,
            tf1h
        )

        print()
        print("=" * 78)
        print("🧠 BOOSTER ANALYSIS")
        print("=" * 78)

        print(
            f"BUY SCORE  : "
            f"{signal['buy_score']}"
        )

        print(
            f"SELL SCORE : "
            f"{signal['sell_score']}"
        )

        print(
            f"EDGE       : "
            f"{signal['edge']}"
        )

        print()

        if signal["grade"] in ("A", "A+"):

            print(
                "🚨 SINAL ENCONTRADO"
            )

            print(
                f"Direção   : "
                f"{signal['direction']}"
            )

            print(
                f"Qualidade : "
                f"{signal['grade']}"
            )

            print(
                f"Expiração candidata: "
                f"{signal['expiry']}"
            )

            print(
                f"Preço     : "
                f"{tf10['price']:.5f}"
            )

            print()
            print("CONFIRMAÇÕES:")

            for reason in signal["reasons"]:
                print(
                    f"  ✅ {reason}"
                )

            save_signal(
                signal,
                tf10,
                tf15,
                tf30,
                tf1h
            )

            print()
            print(
                "💾 Sinal registrado "
                "em signals.csv"
            )

        else:

            print("🚫 SEM ENTRADA")

            if signal["direction"]:
                print(
                    f"Viés atual: "
                    f"{signal['direction']}"
                )

            print()
            print("MOTIVOS:")

            if signal["vetoes"]:
                for veto in signal["vetoes"]:
                    print(
                        f"  ❌ {veto}"
                    )
            else:
                print(
                    "  ❌ Score insuficiente"
                )

        print()
        print("=" * 78)

        print(
            "⚠️ A/A+ são classificações do algoritmo, "
            "não probabilidades de acerto."
        )

        print(
            "🔥 BOOSTER ENGINE FINALIZADO"
        )

    except Exception as error:
        print()
        print("❌ ERRO:")
        print(error)


if __name__ == "__main__":
    main()