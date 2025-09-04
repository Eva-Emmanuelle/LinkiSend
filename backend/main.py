# main.py — LinkiSend backend (liens courts + détails + réclamation sécurisée)
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
import os, secrets, time, re

app = FastAPI(title="LinkiSend API")

# CORS permissif (POC). On restreindra plus tard au domaine frontend.
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
PRICE_USD = { "USDT":1.0,"USDC":1.0,"DAI":1.0,"ETH":1800.0,"BTC":30000.0,"SOL":20.0,"BNB":230.0,"AVAX":12.0,"LINK":6.0 }
RESERVED = {"","docs","openapi.json","favicon.ico","health","create-link","claim","link","s"}

# Mémoire POC
LINKS: Dict[str, Dict[str, Any]] = {}

# ----------------------------
# Helpers
# ----------------------------
ALNUM_RE = re.compile(r"[^\d+]")
HEX40_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$") # approx Solana
EVM_NETWORKS = {"Ethereum","Polygon","BNB Chain","Avalanche","Arbitrum","Optimism"}

def now(): return int(time.time())
def normalize_phone(p:str)->str:
    p = ALNUM_RE.sub("", p or "")
    if p.startswith("00"): p = "+"+p[2:]
    return p
def gen_short_id(n=6):
    alphabet="23456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz"
    return "".join(secrets.choice(alphabet) for _ in range(n))
def is_expired(item): return now()>=item["expires_at"]
def is_evm_address(addr:str)->bool: return bool(HEX40_RE.match(addr or ""))
def is_solana_address(addr:str)->bool: return bool(BASE58_RE.match(addr or ""))
def usd_estimate(amount:float,currency:str)->Optional[float]:
    px = PRICE_USD.get(currency.upper()); return round(amount*px,2) if px else None

# ----------------------------
# Modèles
# ----------------------------
class CreateLinkIn(BaseModel):
    amount: float = Field(...,gt=0)
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
# API
# ----------------------------
@app.get("/health")
def health(): return {"ok":True,"count":len(LINKS)}

@app.post("/create-link",response_model=CreateLinkOut)
def create_link(data:CreateLinkIn):
    sid = gen_short_id()
    while sid in LINKS: sid = gen_short_id()
    payload = data.dict()
    LINKS[sid] = {
        "payload":payload,
        "created_at":now(),
        "expires_at":now()+LINK_TTL_SECONDS,
        "claimed":False,
        "claim":None
    }
    return CreateLinkOut(short_id=sid,expires_in=LINK_TTL_SECONDS)

@app.get("/link/{short_id}")
def link_info(short_id:str):
    item = LINKS.get(short_id)
    if not item: raise HTTPException(404,"Lien introuvable")
    if is_expired(item): raise HTTPException(410,"Lien expiré")
    pl = item["payload"]
    return {
        "short_id":short_id,
        "amount":pl["amount"],
        "currency":pl["currency"],
        "network":pl["network"],
        "recipient_hint":{"last4":pl["recipient_phone"][-4:]},
        "usd":usd_estimate(pl["amount"],pl["currency"]),
        "expires_at":item["expires_at"]
    }

@app.post("/claim",response_model=ClaimOut)
def claim_link(data:ClaimIn):
    sid=data.short_id.strip(); phone=normalize_phone(data.phone); wallet=data.wallet.strip()
    item=LINKS.get(sid)
    if not item: raise HTTPException(404,"Lien introuvable.")
    if is_expired(item): raise HTTPException(410,"Lien expiré.")
    if item["claimed"]: raise HTTPException(409,"Lien déjà réclamé.")
    exp_phone=normalize_phone(item["payload"]["recipient_phone"])
    if phone!=exp_phone: raise HTTPException(403,"Numéro incorrect.")
    net=item["payload"]["network"]
    if net in EVM_NETWORKS and not is_evm_address(wallet): raise HTTPException(400,"Wallet incompatible (EVM requis).")
    if net=="Solana" and not is_solana_address(wallet): raise HTTPException(400,"Wallet incompatible (Solana requis).")
    item["claimed"]=True; item["claim"]={"phone":phone,"wallet":wallet,"claimed_at":now()}
    return ClaimOut(status="ok",short_id=sid,claimed=True,message="🚀 Tes cryptos arrivent !")

@app.get("/s/{short_id}")
def redirect_legacy(short_id:str):
    item=LINKS.get(short_id)
    if not item or is_expired(item): raise HTTPException(404,"Lien invalide ou expiré.")
    return RedirectResponse(f"{FRONTEND_BASE.rstrip('/')}/claim.html?sid={short_id}",status_code=307)

@app.get("/{short_id}")
def redirect_root(short_id:str):
    if short_id in RESERVED: raise HTTPException(404,"Not found.")
    item=LINKS.get(short_id)
    if not item or is_expired(item): raise HTTPException(404,"Lien invalide ou expiré.")
    return RedirectResponse(f"{FRONTEND_BASE.rstrip('/')}/claim.html?sid={short_id}",status_code=307)
