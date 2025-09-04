# main.py — LinkiSend backend (route courte à la racine)
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import Dict, Any
import os, secrets, time

app = FastAPI(title="LinkiSend API")

# CORS permissif (frontend statique + éventuels tests locaux)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# Config
# ----------------------------
# URL publique du FRONTEND pour afficher claim.html (où l’on atterrit après le scan/lien)
# - en local : http://localhost:8001
# - sur Render (ton static site) : ex. https://linkisend-frontend.onrender.com
FRONTEND_BASE = os.getenv("FRONTEND_BASE", "http://localhost:8001")

# Durée de validité par défaut (24h)
LINK_TTL_SECONDS = int(os.getenv("LINK_TTL_SECONDS", "86400"))

# Mots réservés (pour ne pas les traiter comme short_id)
RESERVED = {
    "","docs","openapi.json","favicon.ico","health",
    "create-link","s"  # on garde /s/{id} en compatibilité
}

# Stockage en mémoire (OK pour le POC / démo)
# short_id -> dict(payload)
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
    expires_in: int  # secondes restantes

# ----------------------------
# Helpers
# ----------------------------
def gen_short_id(n: int = 6) -> str:
    # ID court lisible (base32 sans confusions)
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz"
    return "".join(secrets.choice(alphabet) for _ in range(n))

def now() -> int:
    return int(time.time())

def is_expired(item: Dict[str, Any]) -> bool:
    return now() >= item["expires_at"]

# ----------------------------
# API
# ----------------------------
@app.get("/health")
def health():
    return {"ok": True}

@app.post("/create-link", response_model=CreateLinkOut)
def create_link(data: CreateLinkIn):
    short_id = gen_short_id(6)
    # évite collision improbable
    while short_id in LINKS:
        short_id = gen_short_id(6)

    payload = data.dict()
    item = {
        "payload": payload,
        "created_at": now(),
        "expires_at": now() + LINK_TTL_SECONDS,
    }
    LINKS[short_id] = item

    return CreateLinkOut(short_id=short_id, expires_in=LINK_TTL_SECONDS)

# ----------------------------
# Redirections courtes
# ----------------------------
@app.get("/s/{short_id}")  # compat legacy
def redirect_legacy(short_id: str):
    """Compatibilité avec l’ancien schéma /s/{id}."""
    item = LINKS.get(short_id)
    if not item or is_expired(item):
        raise HTTPException(status_code=404, detail="Lien invalide ou expiré.")
    # redirige vers claim.html sur le FRONTEND
    target = f"{FRONTEND_BASE.rstrip('/')}/claim.html?sid={short_id}"
    return RedirectResponse(url=target, status_code=307)

@app.get("/{short_id}")
def redirect_root(short_id: str):
    """
    Nouvelle route courte à la racine : https://linkisend.io/{id}
    On ignore les slugs réservés (docs, create-link, etc.).
    """
    if short_id in RESERVED:
        # Montre quelque chose d’inoffensif si quelqu’un va sur /
        if short_id == "":
            return JSONResponse({"service": "LinkiSend", "status": "ok"})
        raise HTTPException(status_code=404, detail="Not found.")

    item = LINKS.get(short_id)
    if not item or is_expired(item):
        raise HTTPException(status_code=404, detail="Lien invalide ou expiré.")

    target = f"{FRONTEND_BASE.rstrip('/')}/claim.html?sid={short_id}"
    return RedirectResponse(url=target, status_code=307)
