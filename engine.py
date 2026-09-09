from __future__ import annotations

from typing import Any, Dict, List, Optional


# =========================================================
# BOOSTER ENGINE V1.2
# =========================================================

ENGINE_VERSION = "1.2.0"


# =========================================================
# HELPERS
# =========================================================

def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def sma(values: List[float], period: int) -> List[Optional[float]]:
    result: List[Optional[float]] = []

    for i in range(len(values)):
        if i + 1 < period:
            result.append(None)
            continue

        window = values[i - period + 1:i + 1]
        result.append(sum(window) / period)

    return result


def ema(values: List[float], period: int) -> List[Optional[float]]:
    if not values:
        return []

    result: List[Optional[float]] = [None] * len(values)

    if len(values) < period:
        return result

    seed = sum(values[:period]) / period
    result[period - 1] = seed

    multiplier = 2 / (period + 1)
    previous = seed

    for i in range(period, len(values)):
        current = (
            values[i] * multiplier
            + previous * (1 - multiplier)
        )

        result[i] = current
        previous = current

    return result


def rma(values: List[float], period: int) -> List[Optional[float]]:
    result: List[Optional[float]] = [None] * len(values)

    if len(values) < period:
        return result

    seed = sum(values[:period]) / period
    result[period - 1] = seed

    previous = seed

    for i in range(period, len(values)):
        current = (
            (previous * (period - 1))
            + values[i]
        ) / period

        result[i] = current
        previous = current

    return result


# =========================================================
# ATR / DMI / ADX
# =========================================================

def calculate_dmi_adx(
    candles: List[Dict[str, Any]],
    period: int = 14,
) -> Dict[str, List[Optional[float]]]:

    size = len(candles)

    tr = [0.0] * size
    plus_dm = [0.0] * size
    minus_dm = [0.0] * size

    for i in range(1, size):

        high = safe_float(candles[i]["high"])
        low = safe_float(candles[i]["low"])

        prev_high = safe_float(candles[i - 1]["high"])
        prev_low = safe_float(candles[i - 1]["low"])
        prev_close = safe_float(candles[i - 1]["close"])

        tr[i] = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )

        up_move = high - prev_high
        down_move = prev_low - low

        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move

        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move

    atr = rma(tr, period)
    plus_smoothed = rma(plus_dm, period)
    minus_smoothed = rma(minus_dm, period)

    plus_di: List[Optional[float]] = [None] * size
    minus_di: List[Optional[float]] = [None] * size
    dx: List[float] = [0.0] * size

    for i in range(size):

        if (
            atr[i] is None
            or atr[i] == 0
            or plus_smoothed[i] is None
            or minus_smoothed[i] is None
        ):
            continue

        plus = 100 * plus_smoothed[i] / atr[i]
        minus = 100 * minus_smoothed[i] / atr[i]

        plus_di[i] = plus
        minus_di[i] = minus

        denominator = plus + minus

        if denominator > 0:
            dx[i] = (
                100
                * abs(plus - minus)
                / denominator
            )

    adx = rma(dx, period)

    return {
        "atr": atr,
        "plus_di": plus_di,
        "minus_di": minus_di,
        "adx": adx,
    }


# =========================================================
# MACD
# =========================================================

def calculate_macd(
    closes: List[float],
) -> Dict[str, List[Optional[float]]]:

    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)

    macd_line: List[Optional[float]] = [None] * len(closes)

    for i in range(len(closes)):
        if ema12[i] is None or ema26[i] is None:
            continue

        macd_line[i] = ema12[i] - ema26[i]

    valid_macd = [
        value if value is not None else 0.0
        for value in macd_line
    ]

    signal_line = ema(valid_macd, 9)

    histogram: List[Optional[float]] = [None] * len(closes)

    for i in range(len(closes)):
        if (
            macd_line[i] is None
            or signal_line[i] is None
        ):
            continue

        histogram[i] = (
            macd_line[i]
            - signal_line[i]
        )

    return {
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram,
    }


# =========================================================
# FRACTALS CONFIRMADOS
# =========================================================

def confirmed_fractals(
    candles: List[Dict[str, Any]],
) -> Dict[str, Optional[float]]:

    last_high = None
    last_low = None

    if len(candles) < 5:
        return {
            "high": None,
            "low": None,
        }

    for i in range(2, len(candles) - 2):

        high = safe_float(candles[i]["high"])
        low = safe_float(candles[i]["low"])

        if (
            high > safe_float(candles[i - 1]["high"])
            and high > safe_float(candles[i - 2]["high"])
            and high > safe_float(candles[i + 1]["high"])
            and high > safe_float(candles[i + 2]["high"])
        ):
            last_high = high

        if (
            low < safe_float(candles[i - 1]["low"])
            and low < safe_float(candles[i - 2]["low"])
            and low < safe_float(candles[i + 1]["low"])
            and low < safe_float(candles[i + 2]["low"])
        ):
            last_low = low

    return {
        "high": last_high,
        "low": last_low,
    }


# =========================================================
# CANDLE ENGINE
# =========================================================

def candle_metrics(
    candle: Dict[str, Any],
) -> Dict[str, float]:

    open_price = safe_float(candle["open"])
    high = safe_float(candle["high"])
    low = safe_float(candle["low"])
    close = safe_float(candle["close"])

    total_range = max(high - low, 1e-12)
    body = abs(close - open_price)

    upper_wick = (
        high - max(open_price, close)
    )

    lower_wick = (
        min(open_price, close) - low
    )

    body_ratio = body / total_range
    upper_ratio = upper_wick / total_range
    lower_ratio = lower_wick / total_range

    close_position = (
        (close - low) / total_range
    )

    return {
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "range": total_range,
        "body": body,
        "upper_wick": upper_wick,
        "lower_wick": lower_wick,
        "body_ratio": body_ratio,
        "upper_ratio": upper_ratio,
        "lower_ratio": lower_ratio,
        "close_position": close_position,
    }


def analyze_candles(
    candles: List[Dict[str, Any]],
    atr_value: float,
) -> Dict[str, Any]:

    if len(candles) < 6:
        return {
            "buy_score": 0,
            "sell_score": 0,
            "signals": [],
            "indecision": False,
            "explosive": False,
        }

    current = candle_metrics(candles[-1])
    previous = candle_metrics(candles[-2])

    signals: List[str] = []

    buy_score = 0
    sell_score = 0

    # -----------------------------------------------------
    # Rejeição inferior
    # -----------------------------------------------------

    if (
        current["lower_wick"]
        > current["body"] * 1.5
        and current["lower_ratio"] >= 0.40
    ):
        buy_score += 3
        signals.append(
            "rejeição inferior forte"
        )

    # -----------------------------------------------------
    # Rejeição superior
    # -----------------------------------------------------

    if (
        current["upper_wick"]
        > current["body"] * 1.5
        and current["upper_ratio"] >= 0.40
    ):
        sell_score += 3
        signals.append(
            "rejeição superior forte"
        )

    # -----------------------------------------------------
    # Fechamento forte
    # -----------------------------------------------------

    if (
        current["close"] > current["open"]
        and current["body_ratio"] >= 0.60
        and current["close_position"] >= 0.75
    ):
        buy_score += 3
        signals.append(
            "fechamento comprador forte"
        )

    if (
        current["close"] < current["open"]
        and current["body_ratio"] >= 0.60
        and current["close_position"] <= 0.25
    ):
        sell_score += 3
        signals.append(
            "fechamento vendedor forte"
        )

    # -----------------------------------------------------
    # Engolfo
    # -----------------------------------------------------

    bullish_engulfing = (
        previous["close"] < previous["open"]
        and current["close"] > current["open"]
        and current["open"] <= previous["close"]
        and current["close"] >= previous["open"]
    )

    bearish_engulfing = (
        previous["close"] > previous["open"]
        and current["close"] < current["open"]
        and current["open"] >= previous["close"]
        and current["close"] <= previous["open"]
    )

    if bullish_engulfing:
        buy_score += 3
        signals.append(
            "engolfo comprador"
        )

    if bearish_engulfing:
        sell_score += 3
        signals.append(
            "engolfo vendedor"
        )

    # -----------------------------------------------------
    # Sequência das últimas 5 velas
    # -----------------------------------------------------

    recent = candles[-5:]

    bullish_count = sum(
        1
        for candle in recent
        if safe_float(candle["close"])
        > safe_float(candle["open"])
    )

    bearish_count = sum(
        1
        for candle in recent
        if safe_float(candle["close"])
        < safe_float(candle["open"])
    )

    if bullish_count >= 4:
        buy_score += 2
        signals.append(
            "sequência compradora"
        )

    if bearish_count >= 4:
        sell_score += 2
        signals.append(
            "sequência vendedora"
        )

    # -----------------------------------------------------
    # Falha de continuação
    # -----------------------------------------------------

    if (
        previous["close"] > previous["open"]
        and current["close"] < current["open"]
        and current["close"]
        < (
            previous["open"]
            + previous["close"]
        ) / 2
    ):
        sell_score += 2
        signals.append(
            "falha de continuação compradora"
        )

    if (
        previous["close"] < previous["open"]
        and current["close"] > current["open"]
        and current["close"]
        > (
            previous["open"]
            + previous["close"]
        ) / 2
    ):
        buy_score += 2
        signals.append(
            "falha de continuação vendedora"
        )

    # -----------------------------------------------------
    # Candle explosivo
    # -----------------------------------------------------

    explosive = False

    if (
        atr_value > 0
        and current["range"] > atr_value * 1.8
    ):
        explosive = True
        signals.append(
            "candle explosivo"
        )

    # -----------------------------------------------------
    # Indecisão
    # -----------------------------------------------------

    indecision = (
        current["body_ratio"] <= 0.20
        and current["upper_ratio"] >= 0.25
        and current["lower_ratio"] >= 0.25
    )

    if indecision:
        buy_score -= 2
        sell_score -= 2

        signals.append(
            "indecisão"
        )

    return {
        "buy_score": buy_score,
        "sell_score": sell_score,
        "signals": signals,
        "indecision": indecision,
        "explosive": explosive,
        "metrics": current,
    }


# =========================================================
# ANALYZE TIMEFRAME
# =========================================================

def analyze_tf(
    candles: List[Dict[str, Any]],
    timeframe: str,
) -> Dict[str, Any]:

    if len(candles) < 40:
        raise ValueError(
            f"{timeframe}: histórico insuficiente"
        )

    closes = [
        safe_float(candle["close"])
        for candle in candles
    ]

    ema9_series = ema(closes, 9)
    sma20_series = sma(closes, 20)

    dmi = calculate_dmi_adx(
        candles,
        14,
    )

    macd = calculate_macd(
        closes
    )

    fractals = confirmed_fractals(
        candles
    )

    index = len(candles) - 1

    close = closes[index]

    ema9_value = safe_float(
        ema9_series[index]
    )

    sma20_value = safe_float(
        sma20_series[index]
    )

    previous_ema9 = safe_float(
        ema9_series[index - 1]
    )

    previous_sma20 = safe_float(
        sma20_series[index - 1]
    )

    atr = safe_float(
        dmi["atr"][index]
    )

    plus_di = safe_float(
        dmi["plus_di"][index]
    )

    minus_di = safe_float(
        dmi["minus_di"][index]
    )

    adx = safe_float(
        dmi["adx"][index]
    )

    macd_histogram = safe_float(
        macd["histogram"][index]
    )

    ema_slope = (
        ema9_value
        - previous_ema9
    )

    sma_slope = (
        sma20_value
        - previous_sma20
    )

    # -----------------------------------------------------
    # Tendência
    # -----------------------------------------------------

    trend = "NEUTRO"

    if (
        close > ema9_value
        and ema9_value > sma20_value
        and ema_slope > 0
        and sma_slope >= 0
    ):
        trend = "ALTA"

    elif (
        close < ema9_value
        and ema9_value < sma20_value
        and ema_slope < 0
        and sma_slope <= 0
    ):
        trend = "BAIXA"

    # -----------------------------------------------------
    # Candle Engine
    # -----------------------------------------------------

    candle_analysis = analyze_candles(
        candles,
        atr,
    )

    candle_buy = candle_analysis[
        "buy_score"
    ]

    candle_sell = candle_analysis[
        "sell_score"
    ]

    # -----------------------------------------------------
    # Breakout
    # -----------------------------------------------------

    breakout_buy = False
    breakout_sell = False

    if fractals["high"] is not None:
        breakout_buy = (
            close > fractals["high"]
        )

    if fractals["low"] is not None:
        breakout_sell = (
            close < fractals["low"]
        )

    # -----------------------------------------------------
    # Distância da EMA
    # -----------------------------------------------------

    distance_ema_atr = 0.0

    if atr > 0:
        distance_ema_atr = (
            abs(close - ema9_value)
            / atr
        )

    # -----------------------------------------------------
    # Compressão
    # -----------------------------------------------------

    ma_distance_atr = 0.0

    if atr > 0:
        ma_distance_atr = (
            abs(ema9_value - sma20_value)
            / atr
        )

    compression = (
        ma_distance_atr < 0.10
    )

    # -----------------------------------------------------
    # Estado do mercado
    # -----------------------------------------------------

    market_state = "TRANSICAO"

    if (
        adx < 15
        and compression
    ):
        market_state = "LATERAL"

    elif (
        trend == "ALTA"
        and plus_di > minus_di
        and adx >= 18
    ):
        market_state = (
            "CONTINUACAO_ALTA"
        )

    elif (
        trend == "BAIXA"
        and minus_di > plus_di
        and adx >= 18
    ):
        market_state = (
            "CONTINUACAO_BAIXA"
        )

    elif (
        candle_buy >= 4
        and trend in (
            "BAIXA",
            "NEUTRO",
        )
        and plus_di
        >= minus_di * 0.85
    ):
        market_state = (
            "REVERSAO_ALTA"
        )

    elif (
        candle_sell >= 4
        and trend in (
            "ALTA",
            "NEUTRO",
        )
        and minus_di
        >= plus_di * 0.85
    ):
        market_state = (
            "REVERSAO_BAIXA"
        )

    return {
        "timeframe": timeframe,

        "close": close,

        "ema9": ema9_value,
        "sma20": sma20_value,

        "ema_slope": ema_slope,
        "sma_slope": sma_slope,

        "trend": trend,
        "market_state": market_state,

        "atr": atr,

        "plus_di": plus_di,
        "minus_di": minus_di,
        "adx": adx,

        "macd_histogram":
            macd_histogram,

        "fractal_high":
            fractals["high"],

        "fractal_low":
            fractals["low"],

        "breakout_buy":
            breakout_buy,

        "breakout_sell":
            breakout_sell,

        "distance_ema_atr":
            distance_ema_atr,

        "compression":
            compression,

        "candle_score_buy":
            candle_buy,

        "candle_score_sell":
            candle_sell,

        "candle_signals":
            candle_analysis[
                "signals"
            ],

        "indecision":
            candle_analysis[
                "indecision"
            ],

        "explosive":
            candle_analysis[
                "explosive"
            ],
    }


# =========================================================
# SIGNAL ENGINE
# =========================================================

def build_signal(
    tf10: Dict[str, Any],
    tf15: Dict[str, Any],
    tf30: Dict[str, Any],
    tf60: Dict[str, Any],
) -> Dict[str, Any]:

    buy_score = 0
    sell_score = 0

    confirmations: List[str] = []
    warnings: List[str] = []
    vetoes: List[str] = []

    # =====================================================
    # TREND SCORE
    # =====================================================

    trend_weights = {
        "10M": 3,
        "15M": 4,
        "30M": 4,
        "1H": 2,
    }

    timeframes = [
        ("10M", tf10),
        ("15M", tf15),
        ("30M", tf30),
        ("1H", tf60),
    ]

    for label, tf in timeframes:

        weight = trend_weights[label]
        trend = tf.get("trend")

        if trend == "ALTA":
            buy_score += weight
            confirmations.append(
                f"{label} alta"
            )

        elif trend == "BAIXA":
            sell_score += weight
            confirmations.append(
                f"{label} baixa"
            )

    # =====================================================
    # MARKET STATE
    # =====================================================

    states = [
        tf10.get("market_state"),
        tf15.get("market_state"),
        tf30.get("market_state"),
    ]

    continuation_buy = sum(
        state == "CONTINUACAO_ALTA"
        for state in states
    )

    continuation_sell = sum(
        state == "CONTINUACAO_BAIXA"
        for state in states
    )

    reversal_buy = sum(
        state == "REVERSAO_ALTA"
        for state in states
    )

    reversal_sell = sum(
        state == "REVERSAO_BAIXA"
        for state in states
    )

    setup_type = "CONTINUACAO"

    if continuation_buy >= 2:
        buy_score += 4
        confirmations.append(
            "continuação de alta confirmada"
        )

    if continuation_sell >= 2:
        sell_score += 4
        confirmations.append(
            "continuação de baixa confirmada"
        )

    if reversal_buy >= 1:
        buy_score += 3
        setup_type = "REVERSAO"

        confirmations.append(
            "reversão de alta detectada"
        )

    if reversal_sell >= 1:
        sell_score += 3
        setup_type = "REVERSAO"

        confirmations.append(
            "reversão de baixa detectada"
        )

    # =====================================================
    # DMI
    # =====================================================

    plus_di = safe_float(
        tf15.get("plus_di")
    )

    minus_di = safe_float(
        tf15.get("minus_di")
    )

    if plus_di > minus_di * 1.15:
        buy_score += 3

        confirmations.append(
            "DI+ dominante"
        )

    elif minus_di > plus_di * 1.15:
        sell_score += 3

        confirmations.append(
            "DI- dominante"
        )

    # =====================================================
    # MACD
    # =====================================================

    macd10 = safe_float(
        tf10.get(
            "macd_histogram"
        )
    )

    macd15 = safe_float(
        tf15.get(
            "macd_histogram"
        )
    )

    if macd10 > 0 and macd15 > 0:
        buy_score += 2

    elif macd10 < 0 and macd15 < 0:
        sell_score += 2

    # =====================================================
    # CANDLE SCORE
    # =====================================================

    candle_buy = (
        safe_float(
            tf10.get(
                "candle_score_buy"
            )
        )
        +
        safe_float(
            tf15.get(
                "candle_score_buy"
            )
        )
    )

    candle_sell = (
        safe_float(
            tf10.get(
                "candle_score_sell"
            )
        )
        +
        safe_float(
            tf15.get(
                "candle_score_sell"
            )
        )
    )

    if candle_buy > 0:
        buy_score += int(
            candle_buy
        )

    if candle_sell > 0:
        sell_score += int(
            candle_sell
        )

    if candle_buy >= 4:
        confirmations.append(
            "candles favorecem compra"
        )

    if candle_sell >= 4:
        confirmations.append(
            "candles favorecem venda"
        )

    # =====================================================
    # BREAKOUT
    # =====================================================

    breakout_buy = (
        tf10.get("breakout_buy")
        or tf15.get("breakout_buy")
    )

    breakout_sell = (
        tf10.get("breakout_sell")
        or tf15.get("breakout_sell")
    )

    if breakout_buy:
        buy_score += 2

        confirmations.append(
            "rompimento comprador"
        )

    if breakout_sell:
        sell_score += 2

        confirmations.append(
            "rompimento vendedor"
        )

    # =====================================================
    # DIREÇÃO PRELIMINAR
    # =====================================================

    preliminary_direction = None

    if buy_score > sell_score:
        preliminary_direction = "BUY"

    elif sell_score > buy_score:
        preliminary_direction = "SELL"

    # =====================================================
    # V1.2 — CANDLE CONTRÁRIO
    # =====================================================

    contrary_candle_penalty = 0
    contrary_candle_warning = None

    if preliminary_direction == "BUY":

        if candle_sell >= 5:
            vetoes.append(
                "pressão vendedora forte contra BUY"
            )

            contrary_candle_warning = (
                "candles apresentam pressão "
                "vendedora forte"
            )

        elif candle_sell >= 3:
            contrary_candle_penalty = 2

            buy_score = max(
                0,
                buy_score
                - contrary_candle_penalty,
            )

            contrary_candle_warning = (
                "pressão vendedora contrária "
                "reduziu a qualidade do BUY"
            )

            warnings.append(
                contrary_candle_warning
            )

    elif preliminary_direction == "SELL":

        if candle_buy >= 5:
            vetoes.append(
                "pressão compradora forte contra SELL"
            )

            contrary_candle_warning = (
                "candles apresentam pressão "
                "compradora forte"
            )

        elif candle_buy >= 3:
            contrary_candle_penalty = 2

            sell_score = max(
                0,
                sell_score
                - contrary_candle_penalty,
            )

            contrary_candle_warning = (
                "pressão compradora contrária "
                "reduziu a qualidade do SELL"
            )

            warnings.append(
                contrary_candle_warning
            )

    # =====================================================
    # INDECISÃO 15M
    # =====================================================

    if tf15.get("indecision"):

        if preliminary_direction == "BUY":
            buy_score = max(
                0,
                buy_score - 1,
            )

        elif preliminary_direction == "SELL":
            sell_score = max(
                0,
                sell_score - 1,
            )

        warnings.append(
            "indecisão no 15M reduziu a qualidade"
        )

    # =====================================================
    # VETOES
    # =====================================================

    adx15 = safe_float(
        tf15.get("adx")
    )

    adx10 = safe_float(
        tf10.get("adx")
    )

    if adx15 < 18:
        vetoes.append(
            "ADX 15M fraco"
        )

    if adx10 < 12:
        vetoes.append(
            "ADX 10M fraco"
        )

    if (
        tf10.get("market_state")
        == "LATERAL"
        and tf15.get("market_state")
        == "LATERAL"
    ):
        vetoes.append(
            "mercado lateral"
        )

    if tf10.get("indecision"):
        vetoes.append(
            "última vela 10M indecisa"
        )

    if (
        tf10.get("explosive")
        and safe_float(
            tf10.get(
                "distance_ema_atr"
            )
        ) > 1.5
    ):
        vetoes.append(
            "movimento excessivamente esticado"
        )

    # =====================================================
    # SCORE FINAL
    # =====================================================

    buy_score = int(
        max(0, buy_score)
    )

    sell_score = int(
        max(0, sell_score)
    )

    edge = abs(
        buy_score
        - sell_score
    )

    direction = None

    if buy_score > sell_score:
        direction = "BUY"

    elif sell_score > buy_score:
        direction = "SELL"

    # =====================================================
    # GRADE
    # =====================================================

    grade = "BLOQUEADO"

    if (
        direction is not None
        and not vetoes
    ):

        if edge >= 12:
            grade = "A+"

        elif edge >= 8:
            grade = "A"

    if grade == "BLOQUEADO":
        direction = None

    return {
        "direction": direction,
        "grade": grade,

        "buy_score": buy_score,
        "sell_score": sell_score,
        "edge": edge,

        "setup_type":
            setup_type,

        "candle_score_buy":
            int(candle_buy),

        "candle_score_sell":
            int(candle_sell),

        "contrary_candle_penalty":
            contrary_candle_penalty,

        "contrary_candle_warning":
            contrary_candle_warning,

        "confirmations":
            confirmations,

        "warnings":
            warnings,

        "vetoes":
            vetoes,

        "engine_version":
            ENGINE_VERSION,
    }