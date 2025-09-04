# main.py — LinkiSend backend (liens courts + réclamation)
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
import os, secrets, time, re

app = FastAPI(title="LinkiSend API")

# CORS permissif pour le front (on peut restreindre plus tard à ton domaine)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# Config
# ----------------------------
FRONTEND_BASE = os.getenv("FRONTEND_BASE", "http://localhost:8001")
LINK_TTL_SECONDS = int(os.getenv("LINK_TTL_SECONDS", "86400"))  # 24h

RESERVED = {
    "", "docs", "openapi.json", "favicon.ico", "health",
    "create-link", "claim", "claim-status", "s"   # /s conservé pour compat
}

# Stockage en mémoire (POC)
# LINKS[short_id] = {
#   payload: {...}, created_at: int, expires_at: int,
#   claimed: bool, claimed_at: Optional[int], claim: Optional[dict]
# }
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
    # garde + et chiffres, retire le reste
    p = PHONE_RE.sub("", p or "")
    # normalisation simple POC; à durcir plus tard (lib phone)
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

    # Contrôles de base POC
    if not phone or len(phone) < 6:
        raise HTTPException(status_code=400, detail="Numéro de téléphone invalide.")
    if not wallet.lower().startswith("0x") or len(wallet) < 10:
        raise HTTPException(status_code=400, detail="Adresse wallet invalide.")

    # Enregistrer la réclamation (pas d’envoi on-chain dans ce POC)
    item["claimed"] = True
    item["claimed_at"] = now()
    item["claim"] = {
        "phone": phone,
        "wallet": wallet,
    }

    # Ici, plus tard: déclencher le transfert on-chain ou la file d’attente
    return ClaimOut(
        status="ok",
        short_id=sid,
        claimed=True,
        message="Réclamation enregistrée. Le transfert sera traité."
    )

# (Facultatif) statut d’un lien pour debug
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

# ----------------------------
# Redirections courtes
# ----------------------------
@app.get("/s/{short_id}")  # compat legacy
def redirect_legacy(short_id: str):
    item = LINKS.get(short_id)
    if not item or is_expired(item):
        raise HTTPException(status_code=404, detail="Lien invalide ou expiré.")
    target = f"{FRONTEND_BASE.rstrip('/')}/claim.html?sid={short_id}"
    return RedirectResponse(url=target, status_code=307)

@app.get("/{short_id}")
def redirect_root(short_id: str):
    if short_id in RESERVED:
        if short_id == "":
            return JSONResponse({"service": "LinkiSend", "status": "ok"})
        raise HTTPException(status_code=404, detail="Not found.")
    item = LINKS.get(short_id)
    if not item or is_expired(item):
        raise HTTPException(status_code=404, detail="Lien invalide ou expiré.")
    target = f"{FRONTEND_BASE.rstrip('/')}/claim.html?sid={short_id}"
    return RedirectResponse(url=target, status_code=307)
