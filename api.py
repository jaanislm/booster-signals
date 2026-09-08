# ============================================================
# BOOSTER SIGNALS API V2.0
# Scanner multiativos + Supabase
# ============================================================

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from database import save_signal
from scanner import scan_market


# ============================================================
# CONFIGURAÇÕES
# ============================================================

TZ = ZoneInfo("America/Sao_Paulo")

ENGINE_VERSION = "1.0.0"
API_VERSION = "2.0.0"

# Por enquanto:
# A e A+ = expiração de 10 minutos
EXPIRY_MINUTES = 10


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="Booster Signals API",
    description="API do motor Booster Signals multiativos",
    version=API_VERSION
)


# ============================================================
# CORS
# Desenvolvimento apenas.
# Depois restringiremos ao domínio do app.
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# HELPERS
# ============================================================

def now_sp():
    return datetime.now(TZ)


def next_entry_time():
    """
    Define a entrada para o próximo minuto cheio.
    Exemplo:
    14:32:27 -> entrada 14:33:00
    """

    now = now_sp()

    return (
        now.replace(
            second=0,
            microsecond=0
        )
        + timedelta(minutes=1)
    )


def public_ranking_item(asset):
    """
    Converte resultado interno do scanner
    para formato simples para o frontend.
    """

    opportunity = (
        asset["grade"] in ("A", "A+")
        and asset["direction"] in ("BUY", "SELL")
    )

    return {
        "symbol": asset["symbol"],

        "market_type": asset.get(
            "market_type",
            "NORMAL"
        ),

        "direction": asset["direction"],

        "grade": asset["grade"],

        # NÃO é porcentagem de assertividade.
        "score": asset["ranking_score"],

        "price": asset["price"],

        "trend": asset["trends"]["15m"],

        "trends": asset["trends"],

        "adx": asset["adx"],

        "status": (
            "OPPORTUNITY"
            if opportunity
            else "BLOCKED"
        )
    }


# ============================================================
# HOME
# ============================================================

@app.get("/")
def home():

    return {
        "app": "Booster Signals",
        "status": "online",
        "api_version": API_VERSION,
        "engine_version": ENGINE_VERSION,
        "timezone": "America/Sao_Paulo"
    }


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():

    return {
        "status": "ok",
        "api": "online",
        "engine": "online",
        "database": "configured",
        "timestamp": now_sp().isoformat()
    }


# ============================================================
# SCANNER MULTIATIVOS
# ============================================================

@app.get("/scanner")
def scanner():

    try:

        result = scan_market()

        return {
            "success": True,

            "scanned_at":
                result["scanned_at"],

            "assets_scanned":
                result["assets_scanned"],

            "assets_valid":
                result["assets_valid"],

            "opportunities":
                result["opportunities"],

            "best": (
                public_ranking_item(
                    result["best"]
                )
                if result["best"]
                else None
            ),

            "ranking": [
                public_ranking_item(asset)
                for asset in result["ranking"]
            ],

            "errors":
                result.get("errors", [])
        }

    except Exception as error:

        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


# ============================================================
# GERAR SINAL REAL
# ============================================================

@app.post("/generate-signal")
def generate_signal():

    try:

        # ----------------------------------------------------
        # 1. RODAR SCANNER
        # ----------------------------------------------------

        result = scan_market()

        best = result["best"]

        # ----------------------------------------------------
        # 2. NENHUMA OPORTUNIDADE
        # ----------------------------------------------------

        if best is None:

            return {
                "success": True,

                "signal": False,

                "message":
                    "Nenhuma oportunidade A/A+ "
                    "encontrada neste momento.",

                "scanned_at":
                    result["scanned_at"],

                "assets_scanned":
                    result["assets_scanned"],

                "assets_valid":
                    result["assets_valid"],

                "opportunities":
                    0,

                "ranking": [
                    public_ranking_item(asset)
                    for asset in result["ranking"]
                ]
            }

        # ----------------------------------------------------
        # 3. HORÁRIOS
        # ----------------------------------------------------

        entry_time = next_entry_time()

        expiry_time = (
            entry_time
            + timedelta(
                minutes=EXPIRY_MINUTES
            )
        )

        # ----------------------------------------------------
        # 4. PREPARAR SINAL PARA SUPABASE
        # ----------------------------------------------------

        database_signal = {

            "symbol":
                best["symbol"],

            "market_type":
                best.get(
                    "market_type",
                    "NORMAL"
                ),

            "direction":
                best["direction"],

            "grade":
                best["grade"],

            "entry_time":
                entry_time.isoformat(),

            "expiry_time":
                expiry_time.isoformat(),

            "expiry_minutes":
                EXPIRY_MINUTES,

            "entry_price":
                best["price"],

            "buy_score":
                best["buy_score"],

            "sell_score":
                best["sell_score"],

            "edge":
                best["edge"],

            "trend_10m":
                best["trends"]["10m"],

            "trend_15m":
                best["trends"]["15m"],

            "trend_30m":
                best["trends"]["30m"],

            "trend_1h":
                best["trends"]["1h"],

            "adx_10m":
                best["adx"]["10m"],

            "adx_15m":
                best["adx"]["15m"],

            "confirmations":
                best["confirmations"],

            "engine_version":
                ENGINE_VERSION,

            "is_mock":
                False
        }

        # ----------------------------------------------------
        # 5. SALVAR NO SUPABASE
        # ----------------------------------------------------

        saved = save_signal(
            database_signal
        )

        if (
            isinstance(saved, list)
            and len(saved) > 0
        ):
            saved_signal = saved[0]

        else:
            saved_signal = database_signal

        # ----------------------------------------------------
        # 6. RESPOSTA PARA O APP
        # ----------------------------------------------------

        return {

            "success":
                True,

            "signal":
                True,

            "message":
                "Oportunidade encontrada.",

            "data": {

                "id":
                    saved_signal.get("id"),

                "symbol":
                    best["symbol"],

                "market_type":
                    best.get(
                        "market_type",
                        "NORMAL"
                    ),

                "direction":
                    best["direction"],

                "grade":
                    best["grade"],

                # Score interno, NÃO porcentagem.
                "score":
                    best["ranking_score"],

                "entry_time":
                    entry_time.isoformat(),

                "expiry_time":
                    expiry_time.isoformat(),

                "expiry_minutes":
                    EXPIRY_MINUTES,

                "price":
                    best["price"],

                "buy_score":
                    best["buy_score"],

                "sell_score":
                    best["sell_score"],

                "edge":
                    best["edge"],

                "confirmations":
                    best["confirmations"],

                "market": {

                    "10m":
                        best["trends"]["10m"],

                    "15m":
                        best["trends"]["15m"],

                    "30m":
                        best["trends"]["30m"],

                    "1h":
                        best["trends"]["1h"]
                },

                "adx": {

                    "10m":
                        best["adx"]["10m"],

                    "15m":
                        best["adx"]["15m"]
                },

                "engine_version":
                    ENGINE_VERSION,

                "is_mock":
                    False
            },

            "scanner": {

                "scanned_at":
                    result["scanned_at"],

                "assets_scanned":
                    result["assets_scanned"],

                "assets_valid":
                    result["assets_valid"],

                "opportunities":
                    result["opportunities"],

                "ranking": [
                    public_ranking_item(asset)
                    for asset in result["ranking"]
                ]
            }
        }

    except Exception as error:

        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    import uvicorn

    print()
    print("=" * 60)
    print("🔥 BOOSTER SIGNALS API V2.0")
    print("=" * 60)
    print("🚀 API iniciando...")
    print(f"📊 Engine: {ENGINE_VERSION}")
    print("🧠 Scanner multiativos: ATIVO")
    print("🗄️ Supabase: CONFIGURADO")
    print("🕐 Timezone: America/Sao_Paulo")
    print()
    print("📚 Docs:")
    print("http://127.0.0.1:8000/docs")
    print("=" * 60)
    print()

    uvicorn.run(
        "api:app",
        host="127.0.0.1",
        port=8000,
        reload=True
    )