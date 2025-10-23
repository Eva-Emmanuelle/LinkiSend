# main.py — LinkiSend backend (API + frontend statique)
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Dict, Any
from pathlib import Path
import os, secrets, time, re

app = FastAPI(title="LinkiSend API")

# CORS permissif pour le front (à restreindre plus tard au domaine)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# Config
# ----------------------------
BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"  # contient index.html, claim.html, assets, manifest, etc.


FRONTEND_BASE = os.getenv("FRONTEND_BASE", "")  # vide = servir localement
LINK_TTL_SECONDS = int(os.getenv("LINK_TTL_SECONDS", "86400"))  # 24h

RESERVED = {
    "", "docs", "openapi.json", "favicon.ico", "health",
    "create-link", "claim", "claim-status", "s", "assets", "static",
    "manifest.json", "service-worker.js", "config.js", "countries.js", "lang"
}

# ----------------------------
# Stockage POC en mémoire
# ----------------------------
LINKS: Dict[str, Dict[str, Any]] = {}

# ----------------------------
# Modèles
# ----------------------------
class CreateLinkIn(BaseModel):
    amount: float = Field(..., gt=0)
    currency: str
    sender_wallet: str
    recipient_phone: str
    network: str

class CreateLinkOut(BaseModel):
    short_id: str
    expires_in: int

class ClaimIn(BaseModel):
    short_id: str
    phone: str
    wallet: str

class ClaimOut(BaseModel):
    status: str
    short_id: str
    claimed: bool
    message: str

# ----------------------------
# Helpers
# ----------------------------
def gen_short_id(n: int = 6) -> str:
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz"
    return "".join(secrets.choice(alphabet) for _ in range(n))

def now() -> int:
    return int(time.time())

def is_expired(item: Dict[str, Any]) -> bool:
    return now() >= item["expires_at"]

PHONE_RE = re.compile(r"[^\d+]")

def normalize_phone(p: str) -> str:
    p = PHONE_RE.sub("", p or "")
    return p

# ----------------------------
# API
# ----------------------------
@app.get("/health")
def health():
    return {"ok": True, "count": len(LINKS)}

@app.post("/create-link", response_model=CreateLinkOut)
def create_link(data: CreateLinkIn):
    short_id = gen_short_id(6)
    while short_id in LINKS:
        short_id = gen_short_id(6)

    payload = data.dict()
    item = {
        "payload": payload,
        "created_at": now(),
        "expires_at": now() + LINK_TTL_SECONDS,
        "claimed": False,
        "claimed_at": None,
        "claim": None,
    }
    LINKS[short_id] = item
    return CreateLinkOut(short_id=short_id, expires_in=LINK_TTL_SECONDS)

@app.post("/claim", response_model=ClaimOut)
def claim_link(data: ClaimIn):
    sid = data.short_id.strip()
    phone = normalize_phone(data.phone)
    wallet = data.wallet.strip()

    item = LINKS.get(sid)
    if not item:
        raise HTTPException(status_code=404, detail="Lien introuvable.")
    if is_expired(item):
        raise HTTPException(status_code=410, detail="Lien expiré.")
    if item["claimed"]:
        raise HTTPException(status_code=409, detail="Lien déjà réclamé.")

    if not phone or len(phone) < 6:
        raise HTTPException(status_code=400, detail="Numéro de téléphone invalide.")
    if not wallet.lower().startswith("0x") or len(wallet) < 10:
        raise HTTPException(status_code=400, detail="Adresse wallet invalide.")

    item["claimed"] = True
    item["claimed_at"] = now()
    item["claim"] = {"phone": phone, "wallet": wallet}

    return ClaimOut(
        status="ok",
        short_id=sid,
        claimed=True,
        message="Réclamation enregistrée. Le transfert sera traité."
    )

@app.get("/claim-status/{short_id}")
def claim_status(short_id: str):
    item = LINKS.get(short_id)
    if not item:
        raise HTTPException(status_code=404, detail="Lien introuvable.")
    return {
        "short_id": short_id,
        "expired": is_expired(item),
        "claimed": item["claimed"],
        "created_at": item["created_at"],
        "expires_at": item["expires_at"],
        "claim": item["claim"],
    }
# -----------------------
# API CoinGecko relay
# -----------------------
import time, httpx

PRICE_CACHE = {}  # { "symbol": { "ts": timestamp, "usd": float } }
CACHE_TTL = 30    # secondes

@app.get("/price")
def get_price(symbol: str):
    """
    Retourne le prix USD d'un token via CoinGecko, avec cache 30s.
    Exemple : /price?symbol=ETH
    """
    sym = symbol.upper()

    # 1. Vérifier le cache
    now = time.time()
    if sym in PRICE_CACHE and now - PRICE_CACHE[sym]["ts"] < CACHE_TTL:
        return {"symbol": sym, "usd": PRICE_CACHE[sym]["usd"], "cached": True}

    # 2. Mapper symbol -> id CoinGecko
    COINGECKO_IDS = {
        "ETH": "ethereum",
        "BNB": "binancecoin",
        "MATIC": "matic-network",
        "AVAX": "avalanche-2",
        "SOL": "solana",
        "USDT": "tether",
        "USDC": "usd-coin",
        "DAI": "dai",
        "WBTC": "wrapped-bitcoin",
        "LINK": "chainlink",
        "BONK": "bonk",
        "RAY": "raydium",
    }
    if sym not in COINGECKO_IDS:
        raise HTTPException(status_code=400, detail="Token non supporté")

    # 3. Appeler CoinGecko côté serveur
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={COINGECKO_IDS[sym]}&vs_currencies=usd"
    try:
        r = httpx.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        price = data[COINGECKO_IDS[sym]]["usd"]
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erreur CoinGecko: {str(e)}")

    # 4. Mettre à jour le cache
    PRICE_CACHE[sym] = {"ts": now, "usd": price}

    return {"symbol": sym, "usd": price, "cached": False}
# ----------------------------
# Frontend statique
# ----------------------------
if not FRONTEND_BASE:
    # Montages statiques
    app.mount("/assets", StaticFiles(directory=PUBLIC_DIR / "assets"), name="assets")
    app.mount("/static", StaticFiles(directory=PUBLIC_DIR), name="public")

    # Routes explicites
    @app.get("/", include_in_schema=False)
    def serve_index():
        index_file = PUBLIC_DIR / "index.html"
        if not index_file.exists():
            raise HTTPException(status_code=500, detail="index.html manquant.")
        return FileResponse(index_file)

    @app.get("/claim", include_in_schema=False)
    def serve_claim():
        claim_file = PUBLIC_DIR / "claim.html"
        if not claim_file.exists():
            raise HTTPException(status_code=500, detail="claim.html manquant.")
        return FileResponse(claim_file)

    @app.get("/manifest.json", include_in_schema=False)
    def serve_manifest():
        mf = PUBLIC_DIR / "manifest.json"
        if not mf.exists():
            raise HTTPException(status_code=500, detail="manifest.json manquant.")
        return FileResponse(mf)

    @app.get("/service-worker.js", include_in_schema=False)
    def serve_sw():
        sw = PUBLIC_DIR / "service-worker.js"
        if not sw.exists():
            raise HTTPException(status_code=500, detail="service-worker.js manquant.")
        return FileResponse(sw)

# ----------------------------
# Routage par domaine (landing / app / admin)
# ----------------------------
from fastapi import Request

@app.middleware("http")
async def unified_router(request: Request, call_next):
    host = request.headers.get("host", "")
    path = request.url.path

    # Domaine principal -> page d’attente
    if host.startswith("linkisend.io"):
        if path in ["/", ""]:
            landing_file = PUBLIC_DIR / "landing.html"
            if landing_file.exists():
                return FileResponse(landing_file)

    # Sous-domaine admin -> panneau d’administration
    elif host.startswith("admin.linkisend.io"):
        admin_file = PUBLIC_DIR / "admin" / "index.html"
        if admin_file.exists():
            return FileResponse(admin_file)

    # Sinon, comportement normal (PWA ou API)
    response = await call_next(request)
    return response
# ----------------------------
# Authentification admin
# ----------------------------
from fastapi import Form
from fastapi.responses import JSONResponse
import secrets

# Identifiants autorisés
ADMIN_EMAIL = "admin@linkisend.io"
ADMIN_PASS = "X8$kR9!dB7wQ2"  # 🔐 mot de passe fort temporaire

@app.post("/api/admin-login")
async def admin_login(email: str = Form(...), password: str = Form(...)):
    if email.lower() == ADMIN_EMAIL and secrets.compare_digest(password, ADMIN_PASS):
        return JSONResponse({"ok": True, "token": "admin-session-ok"})
    return JSONResponse({"ok": False, "error": "Identifiants invalides."}, status_code=401)
# ----------------------------
# Redirections courtes
# ----------------------------
@app.get("/s/{short_id}")
def redirect_legacy(short_id: str):
    item = LINKS.get(short_id)
    if not item or is_expired(item):
        raise HTTPException(status_code=404, detail="Lien invalide ou expiré.")
    if FRONTEND_BASE:
        target = f"{FRONTEND_BASE.rstrip('/')}/claim.html?sid={short_id}"
        return RedirectResponse(url=target, status_code=307)
    return RedirectResponse(url=f"/claim?sid={short_id}", status_code=307)

@app.get("/{short_id}")
def redirect_root(short_id: str):
    if short_id in RESERVED:
        raise HTTPException(status_code=404, detail="Not found.")
    item = LINKS.get(short_id)
    if not item or is_expired(item):
        raise HTTPException(status_code=404, detail="Lien invalide ou expiré.")
    if FRONTEND_BASE:
        target = f"{FRONTEND_BASE.rstrip('/')}/claim.html?sid={short_id}"
        return RedirectResponse(url=target, status_code=307)
    return RedirectResponse(url=f"/claim?sid={short_id}", status_code=307)
